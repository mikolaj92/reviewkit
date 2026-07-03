import json

from reviewkit.document import SentenceNode
from reviewkit.profile import load_profile
from reviewkit.prompts import sentence_review_prompt
from reviewkit.state import ReviewState


def test_engine_warnings_are_not_leaked_into_the_model_prompt() -> None:
    # state.warnings holds engine-internal diagnostics (dropped malformed model
    # output, action-processing errors). They are our own bookkeeping, not review
    # substance, and must not be fed back into the next level's prompt where the
    # model could react to them.
    profile = load_profile("examples/profiles/story.teacher")
    state = ReviewState(warnings=["Dropped malformed risks list for sentence p1.s1"])

    messages = sentence_review_prompt(
        profile, state, SentenceNode(id="p1.s1", text="Ala ma kota.", paragraph_id="p1")
    )
    user = next(message["content"] for message in messages if message["role"] == "user")

    assert "Dropped malformed risks list" not in user
    payload = json.loads(user.split("\n\n", 1)[1])
    assert "warnings" not in payload["current_review_state"]
