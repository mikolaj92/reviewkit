"""Human-editable profile loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from reviewkit.models import ReviewActionType, ReviewDimension, ReviewScope


class OutputConfig(BaseModel):
    reviewed_docx: bool = True
    corrected_docx: bool = True


class ProtectedPatternConfig(BaseModel):
    name: str
    pattern: str
    preserve: bool = True


class ActionPolicyConfig(BaseModel):
    apply_policy: dict[str, str] = Field(default_factory=dict)
    allowed_action_types_for_auto_apply: list[ReviewActionType] = Field(
        default_factory=lambda: [
            ReviewActionType.REPLACE_TEXT,
            ReviewActionType.DELETE_TEXT,
            ReviewActionType.INSERT_TEXT,
            ReviewActionType.REPLACE,
            ReviewActionType.DELETE,
            ReviewActionType.INSERT_BEFORE,
            ReviewActionType.INSERT_AFTER,
        ]
    )
    block_when_requires_human_decision: bool = True
    require_llm_apply_hint: bool = True
    blocked_categories: list[str] = Field(default_factory=list)
    min_confidence_for_auto_apply: float = 0.85
    max_severity_for_auto_apply: str = "medium"
    max_priority_for_auto_apply: str | None = None
    protected_patterns: list[ProtectedPatternConfig] = Field(default_factory=list)
    auto_apply_requires_unique_match: bool = True
    auto_apply_sensitive_text: bool = False
    ambiguous_edit_behavior: str = "conflict"

    def merged(self, override: "ActionPolicyConfig | None") -> "ActionPolicyConfig":
        if override is None:
            return self
        payload = self.model_dump(mode="json")
        override_payload = override.model_dump(mode="json", exclude_unset=True)
        payload["apply_policy"] = {
            **self.apply_policy,
            **override.apply_policy,
        }
        payload.update(
            {key: value for key, value in override_payload.items() if key != "apply_policy"}
        )
        return ActionPolicyConfig.model_validate(payload)


class ReviewProfile(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    profile_id: str | None = None
    name: str
    display_name: str | None = None
    description: str | None = None
    language: str
    document_type: str
    reviewer_role: str
    review_instructions: str | None = None
    review_dimensions: list[str | ReviewDimension] = Field(default_factory=list)
    review_pipeline: list[ReviewScope] = Field(
        default_factory=lambda: [
            ReviewScope.SENTENCE,
            ReviewScope.PARAGRAPH,
            ReviewScope.SECTION,
            ReviewScope.DOCUMENT,
        ]
    )
    apply_policy: dict[str, str] = Field(default_factory=dict)
    action_policy: ActionPolicyConfig = Field(default_factory=ActionPolicyConfig)
    action_policies: dict[str, ActionPolicyConfig] = Field(default_factory=dict)
    outputs: OutputConfig = Field(default_factory=OutputConfig)
    profile_path: Path | None = None
    markdown_files: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _fill_profile_identity(self) -> "ReviewProfile":
        if self.profile_id is None:
            self.profile_id = self.name
        if self.display_name is None:
            self.display_name = self.name
        return self

    @property
    def instructions_text(self) -> str:
        sections: list[str] = []
        if self.review_instructions:
            sections.append(self.review_instructions.strip())
        for filename, text in self.markdown_files.items():
            sections.append(f"## {filename}\n{text.strip()}")
        return "\n\n".join(sections)

    def resolved_action_policy(self) -> ActionPolicyConfig:
        legacy_policy = ActionPolicyConfig(apply_policy=self.apply_policy)
        base = legacy_policy.merged(self.action_policy)
        document_override = self.action_policies.get(self.document_type)
        named_override = self.action_policies.get(self.name)
        return base.merged(document_override).merged(named_override)


def load_profile(profile_path: str | Path) -> ReviewProfile:
    folder = Path(profile_path)
    yaml_path = folder / "profile.yaml"
    if not folder.is_dir():
        msg = f"Review profile folder does not exist: {folder}"
        raise FileNotFoundError(msg)
    if not yaml_path.is_file():
        msg = f"Review profile is missing profile.yaml: {yaml_path}"
        raise FileNotFoundError(msg)

    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        msg = f"profile.yaml must contain a mapping: {yaml_path}"
        raise ValueError(msg)

    markdown_files = _read_markdown_files(folder)
    payload: dict[str, Any] = {
        **raw,
        "profile_path": folder,
        "markdown_files": markdown_files,
    }
    return ReviewProfile.model_validate(payload)


def _read_markdown_files(folder: Path) -> dict[str, str]:
    files = sorted(
        folder.glob("*.md"), key=lambda path: (path.name != "instructions.md", path.name)
    )
    return {path.name: path.read_text(encoding="utf-8") for path in files}
