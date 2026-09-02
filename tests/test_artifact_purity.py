from docxtor import write_docx_from_paragraphs

from reviewkit import PortableReviewTrailProfile, assess_review_artifact_purity

PROFILE = PortableReviewTrailProfile(heading="Review", intro="Intro")


def test_plain_document_is_clean(tmp_path) -> None:
    path = tmp_path / "plain.docx"
    write_docx_from_paragraphs(path, ("hello",))
    assessment = assess_review_artifact_purity(path, trail_profile=PROFILE)
    assert assessment.is_clean
    assert assessment.inspection_error is None


def test_unreadable_document_fails_closed(tmp_path) -> None:
    path = tmp_path / "broken.docx"
    path.write_bytes(b"not docx")
    assessment = assess_review_artifact_purity(path, trail_profile=PROFILE)
    assert not assessment.is_clean
    assert assessment.inspection_error
