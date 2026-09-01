from reviewkit import (
    RemarkDisposition,
    RemarkWeight,
    ReviewRemark,
    compare_review_remarks,
    remark_disposition,
    remark_weight,
)


def test_comment_semantics() -> None:
    assert remark_weight("RISK: x") is RemarkWeight.SERIOUS
    assert remark_disposition("Status: not_applied") is RemarkDisposition.REJECTED


def test_compare() -> None:
    a = ReviewRemark("1", "Same", RemarkWeight.UNKNOWN, RemarkDisposition.ADVISORY)
    b = ReviewRemark("2", " same ", RemarkWeight.UNKNOWN, RemarkDisposition.ADVISORY)
    result = compare_review_remarks((a,), (b,))
    assert result["left_count"] == 1
    assert result["shared"] == (a,)
