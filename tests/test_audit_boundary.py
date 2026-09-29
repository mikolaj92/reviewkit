from __future__ import annotations

import json
from unittest.mock import Mock

from reviewkit.decision import MockDecisionClient
from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode
from reviewkit.llm import MockLLMClient
from reviewkit.models import (
    ActionStatus,
    FindingLineageEvent,
    ReconciliationDisposition,
    ReviewAction,
    ReviewActionType,
    ReviewFinding,
    ReviewLocator,
    ReviewScope,
)
from reviewkit.pack import Function, Ontology, Pack, Rule
from reviewkit.profile import ReviewProfile
from reviewkit.prompts import section_review_prompt
from reviewkit.state import ReviewState
from reviewkit.takt_reviewer import TaktReviewer
from reviewkit.takt_types import TaktDecision


def _profile() -> ReviewProfile:
    return ReviewProfile(
        name="audit-boundary",
        language="en",
        document_type="generic document",
        reviewer_role="generic reviewer",
        review_pipeline=[ReviewScope.SECTION],
    )


def _section_document(*, text: str = "Current source.") -> ReviewDocument:
    return ReviewDocument(
        sections=[
            SectionNode(
                id="section-1",
                paragraphs=[
                    ParagraphNode(
                        id="p1",
                        text=text,
                        section_id="section-1",
                        locator="body:p:1",
                    )
                ],
            )
        ]
    )


def _section_pack() -> Pack:
    return Pack(
        ontology=Ontology(functions=[Function(id="claim", label="Claim", attach_to=["section"])]),
        units={},
        rules=[
            Rule(
                id="defect-claim",
                kind="defect",
                function_id="claim",
                scope="fragment",
                when="function_present",
            )
        ],
    )


def _state_with_host_audit() -> tuple[ReviewState, ReviewAction]:
    source_text = "source fragment " * 320
    host_event = FindingLineageEvent(
        event_id="host-event-1",
        kind="source",
        scope=ReviewScope.SECTION,
        node_id="section-1",
        locator=ReviewLocator(
            node_id="section-1",
            original_text=source_text,
            text_hash=ReviewLocator.hash_text(source_text),
        ),
        source_digest="source-digest-1",
        detector="BaseLLMDetector",
        model="MockLLMClient",
        profile_digest="profile-digest-1",
    )
    finding = ReviewFinding(
        finding_id="finding-semantic-1",
        node_id="section-1",
        title="Semantic issue",
        description="The source contains a substantive issue.",
        evidence=[{"locator": "body:p:1", "excerpt": source_text}],
        lineage=(host_event,),
        reconciles_finding_id="prior-finding-1",
        reconciliation_disposition=ReconciliationDisposition.ENRICHED,
        metadata={
            "merged_finding_ids": ["host-alias-1"],
            "substantive_finding_note": "preserve this semantic metadata",
        },
    )
    action = ReviewAction(
        id="action-semantic-1",
        finding_id=finding.finding_id,
        scope=ReviewScope.SECTION,
        action_type=ReviewActionType.COMMENT,
        node_id="section-1",
        comment="Review the substantive issue.",
        status=ActionStatus.APPLIED,
        policy_reason="host policy decision",
        lineage=(host_event,),
        metadata={
            "blocked_from_corrected": True,
            "substantive_action_note": "preserve this semantic metadata",
        },
    )
    return ReviewState(findings=[finding]), action


def test_model_prompt_excludes_host_audit_enrichment_but_keeps_semantic_evidence() -> None:
    state, action = _state_with_host_audit()
    section = SectionNode(
        id="section-1",
        paragraphs=[ParagraphNode(id="p1", text="Current source.", section_id="section-1")],
    )

    messages = section_review_prompt(_profile(), state, section, [action])
    payload = json.loads(messages[1]["content"].split("\n\n", 1)[1])
    finding = payload["current_review_state"]["findings"][0]
    projected_action = payload["paragraph_review_results"][0]
    finding_schema = payload["schema"]["$defs"]["ReviewFinding"]["properties"]
    action_schema = payload["schema"]["$defs"]["ReviewAction"]["properties"]

    assert finding["finding_id"] == "finding-semantic-1"
    assert finding["node_id"] == "section-1"
    assert finding["evidence"][0]["excerpt"] == "source fragment " * 320
    assert finding["reconciles_finding_id"] == "prior-finding-1"
    assert finding["reconciliation_disposition"] == "enriched"
    assert finding["metadata"] == {"substantive_finding_note": "preserve this semantic metadata"}
    assert "lineage" not in finding
    assert "host-event-1" not in json.dumps(finding)

    assert projected_action["action_id"] == "action-semantic-1"
    assert projected_action["finding_id"] == "finding-semantic-1"
    assert "lineage" not in projected_action
    assert "status" not in projected_action
    assert "policy_reason" not in projected_action
    assert projected_action["metadata"] == {
        "substantive_action_note": "preserve this semantic metadata"
    }

    assert "lineage" not in finding_schema
    assert "metadata" in finding_schema
    assert "lineage" not in action_schema
    assert "status" not in action_schema
    assert "policy_reason" not in action_schema
    assert "metadata" in action_schema
    assert "FindingLineageEvent" not in payload["schema"]["$defs"]
    assert "FindingReconciliation" not in payload["schema"]["$defs"]
    assert "lineage" in ReviewFinding.model_json_schema()["properties"]
    assert state.findings[0].lineage[0].event_id == "host-event-1"
    assert action.lineage[0].event_id == "host-event-1"
    assert "current_review_state is reference context" in messages[0]["content"]
    assert "explicit document reconciliation" in messages[0]["content"]
    assert "different current node or target is still a distinct finding" in messages[0]["content"]


def test_pack_review_attaches_host_source_lineage() -> None:
    source_text = "Current source."
    decision = MockDecisionClient(
        answers=[{"claim": True}, {"verdict": {"value": "change", "confidence": 0.95}}]
    )
    llm = MockLLMClient(responses=[{"replacement_text": "Updated source."}])
    takt_client = Mock()
    takt_client.evaluate.return_value = TaktDecision(outcome="stable", node_id="section-1")

    findings, actions, state = TaktReviewer(
        profile=_profile(),
        llm=llm,
        pack=_section_pack(),
        decision=decision,
        takt_client=takt_client,
    ).review(_section_document(text=source_text))

    assert len(findings) == 1
    assert findings[0].title == "change"
    assert findings[0].description == "claim"
    assert findings[0].metadata == {}
    assert len(findings[0].lineage) == 1
    assert findings[0].lineage[0].kind == "source"
    assert findings[0].lineage[0].source_digest == ReviewLocator.hash_text(source_text)
    assert findings[0].lineage[0].model == "MockLLMClient"
    assert state.findings[0].lineage == findings[0].lineage

    assert actions
    assert all(event.kind != "reconciliation" for event in actions[0].lineage)
    source_events = [event for event in actions[0].lineage if event.kind == "source"]
    assert source_events
    assert source_events[0].source_digest == ReviewLocator.hash_text(source_text)
    assert llm.calls
    assert all(call.schema.__name__ == "ActionText" for call in llm.calls)


def test_pack_act_actions_receive_host_source_lineage_before_policy() -> None:
    source_text = "Current source."
    decision = MockDecisionClient(
        answers=[{"claim": True}, {"verdict": {"value": "change", "confidence": 0.95}}]
    )
    llm = MockLLMClient(responses=[{"replacement_text": "Updated source."}])
    takt_client = Mock()
    takt_client.evaluate.return_value = TaktDecision(outcome="stable", node_id="section-1")

    _findings, actions, _state = TaktReviewer(
        profile=_profile(),
        llm=llm,
        pack=_section_pack(),
        decision=decision,
        takt_client=takt_client,
    ).review(_section_document(text=source_text))

    source_events = [event for event in actions[0].lineage if event.kind == "source"]
    assert len(source_events) == 1
    assert source_events[0].node_id == "section-1"
    assert source_events[0].source_digest == ReviewLocator.hash_text(source_text)
    assert source_events[0].model == "MockLLMClient"
    assert source_events[0].locator is not None
    assert source_events[0].locator.original_text == source_text
    assert actions[0].lineage[-1].kind == "policy"
    assert actions[0].status is ActionStatus.NEEDS_HUMAN_DECISION
