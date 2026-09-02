import pytest

from reviewkit import ReviewArtifactPreservationError, assert_docx_structure_preserved


def test_unknown_preservation_phase_fails_closed(tmp_path) -> None:
    path = tmp_path / "x.docx"
    path.write_bytes(b"not docx")
    with pytest.raises(ReviewArtifactPreservationError):
        assert_docx_structure_preserved(path, path, phase="other")
