"""Human-editable profile loading.

Profiles are authored as ``profile.toml`` in a folder (plus optional ``*.md``
instruction files). YAML ``profile.yaml`` remains a one-release compatibility
fallback (#3568 / reviewkit 0.15).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from reviewkit.models import ReviewActionType, ReviewDimension, ReviewScope

_PROFILE_TOML = "profile.toml"
_PROFILE_YAML = "profile.yaml"


class OutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed_docx: bool = True
    corrected_docx: bool = True


class ProtectedPatternConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    pattern: str
    preserve: bool = True


class ActionPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    severity_order: dict[str, int] = Field(
        default_factory=lambda: {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    )
    max_priority_for_auto_apply: str | None = None
    priority_order: dict[str, int] = Field(
        default_factory=lambda: {"low": 0, "medium": 1, "high": 2, "critical": 3}
    )
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
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

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
    """Load a review profile folder.

    Preference order (fail-closed if neither exists)::

        profile.toml  (authoritative)
        profile.yaml  (compat fallback for one release)

    When both files exist, TOML wins.
    """
    folder = Path(profile_path)
    if not folder.is_dir():
        msg = f"Review profile folder does not exist: {folder}"
        raise FileNotFoundError(msg)

    toml_path = folder / _PROFILE_TOML
    yaml_path = folder / _PROFILE_YAML
    if toml_path.is_file():
        raw = _load_toml_mapping(toml_path)
        source_path = toml_path
    elif yaml_path.is_file():
        raw = _load_yaml_mapping(yaml_path)
        source_path = yaml_path
    else:
        msg = (
            f"Review profile is missing {_PROFILE_TOML} "
            f"(and no {_PROFILE_YAML} fallback): {folder}"
        )
        raise FileNotFoundError(msg)

    if not isinstance(raw, dict):
        msg = f"{source_path.name} must contain a mapping: {source_path}"
        raise ValueError(msg)

    markdown_files = _read_markdown_files(folder)
    payload: dict[str, Any] = {
        **raw,
        "profile_path": folder,
        "markdown_files": markdown_files,
    }
    return ReviewProfile.model_validate(payload)


def _load_toml_mapping(path: Path) -> dict[str, Any]:
    try:
        loaded = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        msg = f"profile.toml is not valid TOML: {path}: {error}"
        raise ValueError(msg) from error
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        msg = f"profile.toml must contain a mapping: {path}"
        raise ValueError(msg)
    return loaded


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        # Profiles are hand-edited by domain experts; surface a syntax error with the same
        # path-carrying ValueError style as the missing-file/non-mapping cases instead of
        # leaking a bare yaml.YAMLError with no profile context.
        msg = f"profile.yaml is not valid YAML: {path}: {error}"
        raise ValueError(msg) from error
    if not isinstance(raw, dict):
        msg = f"profile.yaml must contain a mapping: {path}"
        raise ValueError(msg)
    return raw


def _read_markdown_files(folder: Path) -> dict[str, str]:
    files = sorted(
        folder.glob("*.md"), key=lambda path: (path.name != "instructions.md", path.name)
    )
    return {path.name: path.read_text(encoding="utf-8") for path in files}
