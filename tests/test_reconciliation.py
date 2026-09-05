from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode, SentenceNode
from reviewkit.models import (
    ReconciliationDisposition,
    ReconciliationRequest,
    ReviewFinding,
    ReviewLocator,
)
from reviewkit.plant import ReviewDocumentPlant
from reviewkit.reconciliation import reconcile_findings, select_reconciliation_targets


def _request(node_id: str, text: str = "Locally correct.") -> ReconciliationRequest:
    return ReconciliationRequest(
        target=ReviewLocator(node_id=node_id, text_hash=ReviewLocator.hash_text(text)),
        reason="A later section contradicts this statement.",
        evidence=("later-section",),
        expected_dimension="consistency",
        finding_ids=("old",),
    )


def _document() -> ReviewDocument:
    sentence = SentenceNode(id="sentence-1", text="Locally correct.", paragraph_id="paragraph-1")
    paragraph = ParagraphNode(
        id="paragraph-1",
        text=sentence.text,
        section_id="section-1",
        sentences=[sentence],
    )
    return ReviewDocument(
        sections=[SectionNode(id="section-1", paragraphs=[paragraph])]
    )


def test_target_selection_is_exact_deduplicated_and_bounded():
    review_document = _document()
    plant = ReviewDocumentPlant(review_document)
    sentence = next(node for node in plant.sequential_scan() if node.kind == "sentence")
    text = review_document.get_node_text(sentence.id) or ""
    valid = _request(sentence.id, text)
    duplicate = _request(sentence.id, text)
    unknown = _request("sentence-not-in-document")

    selected = select_reconciliation_targets(
        [unknown, valid, duplicate],
        {node.id: node for node in plant.sequential_scan()},
        max_nodes=1,
    )

    assert [(request.request_id, node.id) for request, node in selected] == [
        (valid.request_id, sentence.id)
    ]


def test_stale_locator_is_rejected():
    review_document = _document()
    plant = ReviewDocumentPlant(review_document)
    sentence = next(node for node in plant.sequential_scan() if node.kind == "sentence")

    assert select_reconciliation_targets(
        [_request(sentence.id, "stale text")],
        {node.id: node for node in plant.sequential_scan()},
        max_nodes=1,
    ) == []


def test_reconciliation_preserves_id_lineage_and_before_after():
    before = ReviewFinding(
        finding_id="old",
        node_id="sentence-1",
        title="Statement is sound",
        description="No local problem.",
    )
    after = ReviewFinding(
        finding_id="new",
        node_id="sentence-1",
        title="Statement conflicts with conclusion",
        description="Whole-document context changes its meaning.",
        reconciles_finding_id="old",
        reconciliation_disposition=ReconciliationDisposition.SUPERSEDED,
    )
    request = _request("sentence-1")

    result = reconcile_findings([before], [(request, after)])

    assert len(result) == 1
    assert result[0].finding_id == "old"
    assert result[0].reconciliation is not None
    assert result[0].reconciliation.reason == request.reason
    assert result[0].reconciliation.before["title"] == "Statement is sound"
    assert result[0].reconciliation.after["title"] == "Statement conflicts with conclusion"
    assert result[0].lineage[-1].kind == "reconciliation"


def test_conflict_keeps_both_findings():
    before = ReviewFinding(
        finding_id="old", node_id="sentence-1", title="Before", description="Before"
    )
    after = ReviewFinding(
        finding_id="new",
        node_id="sentence-1",
        title="After",
        description="After",
        reconciles_finding_id="old",
        reconciliation_disposition=ReconciliationDisposition.CONFLICT,
    )

    result = reconcile_findings([before], [(_request("sentence-1"), after)])

    assert [finding.finding_id for finding in result] == ["old", "new"]
    assert result[1].reconciliation.disposition == ReconciliationDisposition.CONFLICT
