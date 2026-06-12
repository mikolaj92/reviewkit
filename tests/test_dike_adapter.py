from reviewkit.adapters.dike import actions_from_dike_report
from reviewkit.models import ReviewActionType, ReviewScope


def test_dike_report_findings_map_to_review_actions() -> None:
    actions = actions_from_dike_report(
        {
            "findings": [
                {
                    "rule_code": "LB-EMP-001",
                    "severity": "high",
                    "title": "Employer or employee identification is missing",
                    "summary": "The labor document does not identify parties clearly.",
                    "legal_basis": [
                        {
                            "source": "Kodeks pracy",
                            "article": "29",
                            "clause": "par. 1",
                            "note": "strony stosunku pracy",
                        }
                    ],
                    "recommendation": {
                        "code": "REC-LB-EMP-001",
                        "title": "Add labor-party identification",
                        "action": "Insert employer and employee identification.",
                    },
                    "evidence_refs": [
                        {
                            "segment_id": "body:p:0",
                            "locator": "body:p:0",
                            "excerpt": "Umowa o pracę",
                        }
                    ],
                    "missing_elements": [
                        {
                            "code": "employment_parties",
                            "description": "Employer and employee identification",
                        }
                    ],
                }
            ]
        }
    )

    assert len(actions) == 1
    action = actions[0]
    assert action.source_system == "dike"
    assert action.scope == ReviewScope.PARAGRAPH
    assert action.node_id == "p1"
    assert action.action_type == ReviewActionType.RISK
    assert action.references[0].label == "Kodeks pracy 29 par. 1"
    assert action.evidence_refs[0].excerpt == "Umowa o pracę"
