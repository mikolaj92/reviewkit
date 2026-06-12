from pathlib import Path

from reviewkit.profile import load_profile


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
