from pathlib import Path

import pytest

from reviewkit.profile import load_profile


def test_malformed_yaml_raises_value_error_with_path(tmp_path: Path) -> None:
    # A YAML syntax error must surface with the same path-carrying ValueError style as the
    # other load_profile failures, not leak a bare yaml.YAMLError with no profile context.
    (tmp_path / "profile.yaml").write_text("name: broken\n  bad: [unclosed\n", encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        load_profile(tmp_path)

    assert "profile.yaml is not valid YAML" in str(excinfo.value)
    assert str(tmp_path / "profile.yaml") in str(excinfo.value)


def test_profile_loads_from_folder() -> None:
    profile = load_profile(Path("examples/profiles/story.teacher"))

    assert profile.name == "story.teacher"
    assert profile.language == "pl"
    assert profile.apply_policy["typo"] == "apply"
    assert "instructions.md" in profile.markdown_files
    assert "nauczyciel" in profile.instructions_text


def test_profile_resolves_document_type_action_policy() -> None:
    profile = load_profile(Path("examples/profiles/story.teacher"))
    policy = profile.resolved_action_policy()

    assert policy.apply_policy["typo"] == "apply"
    assert policy.max_severity_for_auto_apply == "medium"


def test_example_profile_embodies_fail_closed_auto_apply_defaults() -> None:
    # The canonical example is copied by users, so it must model the fail-closed contract:
    # never auto-apply an edit on unhinted or zero-confidence model output.
    policy = load_profile(Path("examples/profiles/story.teacher")).resolved_action_policy()

    assert policy.require_llm_apply_hint is True
    assert policy.min_confidence_for_auto_apply > 0.0
