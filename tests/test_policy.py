from reviewkit.models import ActionStatus, ReviewAction, ReviewActionType, ReviewScope
from reviewkit.policy import ActionPolicy
from reviewkit.profile import ActionPolicyConfig


def test_priority_order_can_be_supplied_by_caller() -> None:
    policy = ActionPolicy(
        ActionPolicyConfig(
            apply_policy={"typo": "apply"},
            max_priority_for_auto_apply="p1",
            priority_order={"p0": 0, "p1": 1, "p2": 2},
        )
    )

    decision = policy.decide(_text_edit(priority="p2"), node_text="bad")

    assert decision.status == ActionStatus.NEEDS_HUMAN_DECISION
    assert "exceeds policy threshold" in decision.reason


def test_default_priority_order_preserves_neutral_labels() -> None:
    policy = ActionPolicy(
        ActionPolicyConfig(
            apply_policy={"typo": "apply"},
            max_priority_for_auto_apply="medium",
        )
    )

    decision = policy.decide(_text_edit(priority="high"), node_text="bad")

    assert decision.status == ActionStatus.NEEDS_HUMAN_DECISION


def _text_edit(*, priority: str) -> ReviewAction:
    return ReviewAction(
        scope=ReviewScope.SENTENCE,
        action_type=ReviewActionType.REPLACE,
        node_id="p1.s1",
        original_text="bad",
        replacement_text="good",
        category="typo",
        priority=priority,
        confidence=1.0,
    )
