# ReviewKit

ReviewKit is a domain-agnostic Python framework for document review.
It is not a legal checker, grammar checker or one-shot document correction tool.
Applications provide review profiles, LLM clients and optional context; ReviewKit validates
the resulting findings/actions and applies only safe deterministic edits.

It reviews documents in layers:

```text
sentence -> paragraph -> section -> document
```

It can produce three outputs:

- `reviewed.docx` with every correction, suggestion, question and risk marked for human review.
- `corrected.docx` as a clean fully corrected document with text edits applied and no review markers.
- a JSON report with findings, actions, statuses, policy reasons and aggregate metrics.

## Principles

1. The LLM is replaceable.
2. Profiles are YAML/Markdown folders and can define arbitrary review dimensions.
3. Review is hierarchical, not one-shot.
4. Findings describe observations; actions describe what might be done about them.
5. The library validates and applies actions deterministically.
6. Auto-apply is conservative by default and ambiguous edits become conflicts.
7. DOCX and JSON reports are first-class outputs.

## Install and Run

```bash
uv sync
uv run reviewkit input.docx \
  --profile examples/profiles/story.teacher \
  --out-reviewed reviewed.docx \
  --out-corrected corrected.docx
```

The CLI currently uses `MockLLMClient`, because ReviewKit does not assume a provider.
Production integrations should pass their own implementation of `LLMClient`.

## Python API

```python
from reviewkit import review_document
from reviewkit.llm import MockLLMClient

result = review_document(
    input_path="input.docx",
    profile_path="examples/profiles/story.teacher",
    llm=MockLLMClient(),
    out_reviewed="reviewed.docx",
    out_corrected="corrected.docx",
)

result.save_json("review-report.json")

for finding in result.findings:
    print(finding.finding_id, finding.dimension, finding.title)

for action in result.actions:
    print(action.action_id, action.status, action.policy_reason)
```

## LLM Interface

```python
from typing import Protocol
from pydantic import BaseModel


class LLMClient(Protocol):
    def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
    ) -> BaseModel:
        ...
```

## Review Profiles

Profiles are folders, not Python objects:

```text
profiles/employment-contract.lawyer/
  profile.yaml
  instructions.md
  required-clauses.md
  risky-clauses.md
```

`profile.yaml` defines role, language, document type, pipeline, dimensions and action policy.
Markdown files contain reviewer instructions that can be edited by domain experts.

Profiles are intentionally generic:

```yaml
profile_id: internal-policy-review
name: internal-policy-review
display_name: Internal policy review
language: en
document_type: policy memo
reviewer_role: compliance reviewer
review_dimensions:
  - clarity
  - id: internal_policy
    label: Internal policy
    metadata:
      owner: ops
review_instructions: |
  Review only against the caller-provided criteria.
action_policy:
  apply_policy:
    typo: apply
  require_llm_apply_hint: true
  min_confidence_for_auto_apply: 0.85
  max_severity_for_auto_apply: medium
```

The default action policy does not silently rewrite text. A write action must be allowed by
policy, carry enough confidence, have an explicit apply hint, pass protected-pattern checks
and avoid sensitive-looking text changes unless the profile opts in. Stale locators and
non-unique text matches are reported as conflicts instead of being applied.

## Findings, Actions and JSON Reports

`ReviewFinding` captures what the reviewer observed: dimension, severity, evidence and
rationale. `ReviewAction` captures a possible response: comment, replacement, insertion,
deletion, flag or domain-specific advisory action. Actions may reference findings with
`finding_id`, but the two are serialized separately.

`ReviewResult.save_json(path)` writes a report shaped for downstream systems:

- `findings` and `actions` as separate arrays;
- `actions_by_type`, `actions_by_status`, `findings_by_dimension` and `findings_by_severity`;
- `applied_actions`, `skipped_actions` and `conflicts`;
- generated artifact paths and warnings.

## DOCX Rendering

`reviewed.docx` starts from the source DOCX and patches reviewed paragraphs in place:

- body, table, header and footer paragraphs keep the original document structure;
- text edits are written as native `w:ins` / `w:del` tracked changes around the changed text;
- review notes are anchored as Word comments on the reviewed fragment when possible.
- `corrected.docx` applies deterministic text-edit actions into a clean document.
- Conflicts and hard safety-guard violations are not applied to `corrected.docx`.

## Extension Points

ReviewKit keeps domain logic outside the core. Legal, editorial, educational or internal
policy behavior belongs in profiles, context providers or adapters, not in the framework.
Existing extension points include:

- per-document-type `action_policy` / `action_policies` in profile YAML,
- policy reasons, source-system tags, evidence refs and references on `ReviewAction`,
- protected-pattern guards for corrected output safety,
- `ReviewContextProvider` for grounding, classifier results or external evidence.

## Limitations

- ReviewKit does not decide whether an edit is legally, medically or contractually correct.
- ReviewKit does not require or bundle a single LLM provider.
- Corrected output is deterministic text editing, not a whole-document rewrite.
- Ambiguous edits, stale locators and sensitive-looking replacements are blocked for human
  review unless a profile explicitly relaxes the policy.

## Contributors

- [mikolaj92](https://github.com/mikolaj92)
- [PSyron](https://github.com/PSyron)

## License

ReviewKit is released under the MIT License. See [LICENSE](LICENSE).
