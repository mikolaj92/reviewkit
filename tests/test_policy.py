import pytest

from reviewkit.models import ActionStatus, ReviewAction, ReviewActionType, ReviewScope, ReviewStats
from reviewkit.policy import ActionPolicy
from reviewkit.profile import ActionPolicyConfig


@pytest.mark.parametrize(
    "action_type",
    [
        ReviewActionType.COMMENT,
        ReviewActionType.SUGGESTION,
        ReviewActionType.PRAISE,
        ReviewActionType.SUMMARY,
    ],
)
def test_required_advisory_actions_need_human_decision_by_default(
    action_type: ReviewActionType,
) -> None:
    action = ReviewAction(
        id="a1",
        scope=ReviewScope.SENTENCE,
        action_type=action_type,
        node_id="p1.s1",
        category="X-001",
        comment="Requires a reviewer decision.",
        requires_human_decision=True,
        confidence=1.0,
    )
    policy = ActionPolicy(
        ActionPolicyConfig(apply_policy={}, block_when_requires_human_decision=True)
    )

    decision = policy.decide(action, node_text="Example text.")

    assert decision.status == ActionStatus.NEEDS_HUMAN_DECISION
    action.status = decision.status
    assert ReviewStats.from_actions([action]).human_decision_count == 1


def test_explicit_advisory_category_policy_still_wins() -> None:
    action = ReviewAction(
        id="a1",
        scope=ReviewScope.SENTENCE,
        action_type=ReviewActionType.COMMENT,
        node_id="p1.s1",
        category="X-001",
        comment="Advisory by explicit category policy.",
        requires_human_decision=True,
        confidence=1.0,
    )
    policy = ActionPolicy(
        ActionPolicyConfig(
            apply_policy={"X-001": "comment"},
            block_when_requires_human_decision=True,
        )
    )

    decision = policy.decide(action, node_text="Example text.")

    assert decision.status == ActionStatus.NOT_APPLIED
