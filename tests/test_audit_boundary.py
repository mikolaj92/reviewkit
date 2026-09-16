from __future__ import annotations

import json
from unittest.mock import Mock

from reviewkit.actions import should_apply_to_corrected
from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode
from reviewkit.llm import MockLLMClient
from reviewkit.models import (
    ActionStatus,
    DocumentReviewResponse,
    FindingLineageEvent,
    ReconciliationDisposition,
    ReviewAction,
    ReviewActionType,
    ReviewFinding,
    ReviewLocator,
    ReviewScope,
)
from reviewkit.profile import ActionPolicyConfig, ReviewProfile
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
    assert finding["metadata"] == {
        "substantive_finding_note": "preserve this semantic metadata"
    }
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


def test_host_rebuilds_audit_after_model_fields_are_normalized() -> None:
    source_text = "semantic evidence " * 320
    model_lineage = {
        "event_id": "model-event-must-not-survive",
        "kind": "source",
        "scope": "section",
        "node_id": "section-1",
        "source_digest": "model-digest-must-not-survive",
    }
    llm = MockLLMClient(
        responses=[
            {
                "findings": [
                    {
                        "finding_id": "finding-1",
                        "node_id": "section-1",
                        "title": "Substantive issue",
                        "description": "The source needs review.",
                        "evidence": [{"locator": "body:p:1", "excerpt": source_text}],
                        "lineage": [model_lineage],
                        "metadata": {"substantive_note": "keep this"},
                    }
                ],
                "actions": [
                    {
                        "id": "action-1",
                        "finding_id": "finding-1",
                        "scope": "section",
                        "action_type": "comment",
                        "node_id": "section-1",
                        "comment": "Review this issue.",
                        "status": "applied",
                        "policy_reason": "model policy must not survive",
                        "lineage": [model_lineage],
                    }
                ],
            },
            {"summary": "document checked"},
        ]
    )
    takt_client = Mock()
    takt_client.evaluate.return_value = TaktDecision(outcome="stable", node_id="section-1")
    profile = ReviewProfile(
        name="audit-boundary",
        language="en",
        document_type="generic document",
        reviewer_role="generic reviewer",
        review_pipeline=[ReviewScope.SECTION, ReviewScope.DOCUMENT],
    )
    document = ReviewDocument(
        sections=[
            SectionNode(
                id="section-1",
                paragraphs=[
                    ParagraphNode(
                        id="p1",
                        text="Current source.",
                        section_id="section-1",
                        locator="body:p:1",
                    )
                ],
            )
        ]
    )

    findings, actions, state = TaktReviewer(
        profile=profile,
        llm=llm,
        takt_client=takt_client,
    ).review(document)

    assert len(findings) == 1
    assert findings[0].finding_id == "finding-1"
    assert findings[0].evidence[0].excerpt == source_text
    assert findings[0].metadata == {"substantive_note": "keep this"}
    assert len(findings[0].lineage) == 1
    assert findings[0].lineage[0].event_id != "model-event-must-not-survive"
    assert findings[0].lineage[0].source_digest != "model-digest-must-not-survive"
    assert actions[0].status is ActionStatus.NOT_APPLIED
    assert all(event.event_id != "model-event-must-not-survive" for event in actions[0].lineage)
    assert state.findings[0].lineage == findings[0].lineage
    document_call = next(call for call in llm.calls if call.schema is DocumentReviewResponse)
    assert "model-event-must-not-survive" not in document_call.content
    assert source_text in document_call.content


def test_model_metadata_reserved_keys_are_sanitized_at_host_boundary() -> None:
    document = ReviewDocument(
        sections=[
            SectionNode(
                id="section-1",
                paragraphs=[
                    ParagraphNode(
                        id="p1",
                        text="Current source.",
                        section_id="section-1",
                        locator="body:p:1",
                    )
                ],
            )
        ]
    )
    llm = MockLLMClient(
        responses=[
            {
                "findings": [
                    {
                        "finding_id": "finding-1",
                        "node_id": "section-1",
                        "title": "Substantive issue",
                        "description": "The source needs review.",
                        "metadata": {
                            "merged_finding_ids": ["ghost-alias"],
                            "reconciliation_request_id": "fake-request",
                            "real_finding_field": "must-survive",
                        },
                    }
                ],
                "actions": [
                    {
                        "id": "action-1",
                        "finding_id": "finding-1",
                        "scope": "section",
                        "action_type": "replace",
                        "node_id": "section-1",
                        "original_text": "Current",
                        "replacement_text": "Updated",
                        "category": "typo",
                        "confidence": 0.95,
                        "apply_hint": True,
                        "metadata": {
                            "blocked_from_corrected": True,
                            "real_action_field": "must-survive",
                        },
                    }
                ],
            }
        ]
    )
    takt_client = Mock()
    takt_client.evaluate.return_value = TaktDecision(outcome="actuation", node_id="section-1")
    profile = ReviewProfile(
        name="audit-boundary-metadata",
        language="en",
        document_type="generic document",
        reviewer_role="generic reviewer",
        review_pipeline=[ReviewScope.SECTION],
        action_policy=ActionPolicyConfig(apply_policy={"typo": "apply"}),
    )

    findings, actions, _state = TaktReviewer(
        profile=profile,
        llm=llm,
        takt_client=takt_client,
    ).review(document)

    assert findings[0].metadata == {"real_finding_field": "must-survive"}
    assert actions[0].metadata == {"real_action_field": "must-survive"}
    assert should_apply_to_corrected(actions[0])


def test_standalone_action_gets_host_source_lineage_after_model_lineage_is_removed() -> None:
    document = ReviewDocument(
        sections=[
            SectionNode(
                id="section-1",
                paragraphs=[
                    ParagraphNode(
                        id="p1",
                        text="Current source.",
                        section_id="section-1",
                        locator="body:p:1",
                    )
                ],
            )
        ]
    )
    llm = MockLLMClient(
        responses=[
            {
                "actions": [
                    {
                        "id": "standalone-action",
                        "scope": "section",
                        "action_type": "comment",
                        "node_id": "section-1",
                        "comment": "Review this source.",
                        "lineage": [
                            {
                                "event_id": "model-event-must-not-survive",
                                "kind": "source",
                                "scope": "section",
                                "node_id": "section-1",
                            }
                        ],
                    }
                ]
            }
        ]
    )
    takt_client = Mock()
    takt_client.evaluate.return_value = TaktDecision(outcome="stable", node_id="section-1")
    profile = ReviewProfile(
        name="audit-boundary-standalone-action",
        language="en",
        document_type="generic document",
        reviewer_role="generic reviewer",
        review_pipeline=[ReviewScope.SECTION],
    )

    findings, actions, _state = TaktReviewer(
        profile=profile,
        llm=llm,
        takt_client=takt_client,
    ).review(document)

    assert not findings
    source_events = [event for event in actions[0].lineage if event.kind == "source"]
    assert len(source_events) == 1
    assert source_events[0].node_id == "section-1"
    assert source_events[0].source_digest == ReviewLocator.hash_text("Current source.")
    assert source_events[0].model == "MockLLMClient"
    assert source_events[0].action_id == "standalone-action"
    assert all(event.event_id != "model-event-must-not-survive" for event in actions[0].lineage)
    assert actions[0].lineage[-1].kind == "policy"


def test_reconciliation_actions_get_host_source_lineage_before_policy_audit() -> None:
    document = ReviewDocument(
        sections=[
            SectionNode(
                id="section-1",
                paragraphs=[
                    ParagraphNode(
                        id="p1",
                        text="Current source.",
                        section_id="section-1",
                        locator="body:p:1",
                    )
                ],
            )
        ]
    )
    model_lineage = {
        "event_id": "reconciliation-model-event-must-not-survive",
        "kind": "source",
        "scope": "section",
        "node_id": "section-1",
    }
    llm = MockLLMClient(
        responses=[
            {
                "findings": [
                    {
                        "finding_id": "initial",
                        "node_id": "section-1",
                        "title": "Initial assessment",
                        "description": "The local text looked consistent.",
                    }
                ]
            },
            {
                "reconciliation_requests": [
                    {
                        "request_id": "request-1",
                        "target": {
                            "node_id": "section-1",
                            "text_hash": ReviewLocator.hash_text("Current source."),
                        },
                        "reason": "A later whole-document observation changes the context.",
                        "evidence": ["document-context-1"],
                        "expected_dimension": "consistency",
                        "finding_ids": ["initial"],
                    }
                ]
            },
            {
                "findings": [
                    {
                        "finding_id": "reconciled",
                        "node_id": "section-1",
                        "title": "Reconciled assessment",
                        "description": "The whole-document context changes the result.",
                        "reconciles_finding_id": "initial",
                        "reconciliation_disposition": "superseded",
                        "evidence": [{"locator": "body:p:1", "excerpt": "Current source."}],
                        "lineage": [model_lineage],
                    }
                ],
                "actions": [
                    {
                        "id": "recon-standalone",
                        "scope": "section",
                        "action_type": "comment",
                        "node_id": "section-1",
                        "comment": "Review the reconciled source.",
                        "lineage": [model_lineage],
                    },
                    {
                        "id": "recon-linked",
                        "finding_id": "reconciled",
                        "scope": "section",
                        "action_type": "comment",
                        "node_id": "section-1",
                        "comment": "Review the reconciled finding.",
                        "lineage": [model_lineage],
                    },
                ],
            },
        ]
    )
    takt_client = Mock()
    takt_client.evaluate.return_value = TaktDecision(outcome="stable", node_id="section-1")
    profile = ReviewProfile(
        name="audit-boundary-reconciliation-actions",
        language="en",
        document_type="generic document",
        reviewer_role="generic reviewer",
        review_pipeline=[ReviewScope.SECTION, ReviewScope.DOCUMENT],
        reconciliation_max_rounds=1,
        reconciliation_max_nodes=1,
    )

    findings, actions, _state = TaktReviewer(
        profile=profile,
        llm=llm,
        takt_client=takt_client,
    ).review(document)

    assert len(llm.calls) == 3
    assert [finding.finding_id for finding in findings] == ["initial"]
    final_finding = findings[0]
    assert final_finding.reconciliation is not None
    assert final_finding.reconciliation.request_id == "request-1"
    assert final_finding.lineage[-1].kind == "reconciliation"
    reconciliation_sources = [event for event in final_finding.lineage if event.kind == "source"]
    assert len(reconciliation_sources) == 2
    assert reconciliation_sources[-1].node_id == "section-1"
    assert reconciliation_sources[-1].source_digest == ReviewLocator.hash_text("Current source.")
    assert reconciliation_sources[-1].model == "MockLLMClient"
    assert reconciliation_sources[-1].profile_digest

    actions_by_id = {action.id: action for action in actions}
    assert actions_by_id["recon-linked"].finding_id == "initial"
    for action in actions:
        source_events = [event for event in action.lineage if event.kind == "source"]
        assert len(source_events) == 1
        assert source_events[0].node_id == "section-1"
        assert source_events[0].locator is not None
        assert source_events[0].locator.original_text == "Current source."
        assert source_events[0].source_digest == ReviewLocator.hash_text("Current source.")
        assert source_events[0].model == "MockLLMClient"
        assert source_events[0].profile_digest
        assert all(
            event.event_id != "reconciliation-model-event-must-not-survive"
            for event in action.lineage
        )
        assert action.lineage[-1].kind == "policy"


def test_reconciliation_request_and_identity_survive_model_boundary() -> None:
    document = ReviewDocument(
        sections=[
            SectionNode(
                id="section-1",
                paragraphs=[
                    ParagraphNode(
                        id="p1",
                        text="Current source.",
                        section_id="section-1",
                        locator="body:p:1",
                    )
                ],
            )
        ]
    )
    llm = MockLLMClient(
        responses=[
            {
                "findings": [
                    {
                        "finding_id": "old-finding",
                        "node_id": "section-1",
                        "title": "Initial assessment",
                        "description": "The local text looked consistent.",
                    }
                ],
            },
            {
                "reconciliation_requests": [
                    {
                        "request_id": "request-1",
                        "target": {
                            "node_id": "section-1",
                            "text_hash": ReviewLocator.hash_text("Current source."),
                        },
                        "reason": "A later whole-document observation changes the context.",
                        "evidence": ["document-context-1"],
                        "expected_dimension": "consistency",
                        "finding_ids": ["old-finding"],
                    }
                ],
            },
            {
                "findings": [
                    {
                        "finding_id": "new-finding",
                        "node_id": "section-1",
                        "title": "Reconciled assessment",
                        "description": "The whole-document context changes the result.",
                        "reconciles_finding_id": "old-finding",
                        "reconciliation_disposition": "superseded",
                        "evidence": [{"locator": "body:p:1", "excerpt": "Current source."}],
                    }
                ]
            },
        ]
    )
    takt_client = Mock()
    takt_client.evaluate.return_value = TaktDecision(outcome="stable", node_id="section-1")
    profile = ReviewProfile(
        name="audit-boundary-reconciliation",
        language="en",
        document_type="generic document",
        reviewer_role="generic reviewer",
        review_pipeline=[ReviewScope.SECTION, ReviewScope.DOCUMENT],
        reconciliation_max_rounds=1,
        reconciliation_max_nodes=1,
    )

    findings, _actions, _state = TaktReviewer(
        profile=profile,
        llm=llm,
        takt_client=takt_client,
    ).review(document)

    assert [finding.finding_id for finding in findings] == ["old-finding"]
    assert findings[0].reconciliation is not None
    assert findings[0].reconciliation.request_id == "request-1"
    assert findings[0].reconciliation.disposition is ReconciliationDisposition.SUPERSEDED
    assert findings[0].reconciles_finding_id == "old-finding"
    assert findings[0].lineage[-1].kind == "reconciliation"
