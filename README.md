# ReviewKit

ReviewKit is not a one-shot document correction tool.
It is a hierarchical human-like review workflow engine.

It reviews documents in layers:

```text
sentence -> paragraph -> section -> document
```

It produces two human-facing outputs:

- `reviewed.docx` with every correction, suggestion, question and risk marked for human review.
- `corrected.docx` as a clean fully corrected document with text edits applied and no review markers.

## Principles

1. The LLM is replaceable.
2. Profiles are YAML/Markdown folders for non-technical reviewers.
3. Review is hierarchical, not one-shot.
4. The LLM generates review actions, not finished documents.
5. The library applies actions deterministically.
6. The end user receives `reviewed.docx` and `corrected.docx`.
7. JSON and internal models are implementation details, not the primary user interface.

## Install and Run

```bash
uv sync
uv run reviewkit review input.docx \
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

`profile.yaml` defines role, language, document type, pipeline and apply policy.
Markdown files contain reviewer instructions that can be edited by teachers, lawyers or editors.

## DOCX Rendering

`python-docx` does not expose native Track Changes as a high-level API. The first renderer is
therefore pragmatic:

- `reviewed.docx` uses inline markers for text edits and Word comments when available.
- `corrected.docx` applies deterministic text-edit actions into a clean document.
- Conflicts and hard safety-guard violations are not applied to `corrected.docx`.

The renderer module contains a TODO where this can be replaced with true Word Track Changes /
OpenXML support.

## Dike-Inspired Extension Points

ReviewKit keeps domain logic outside the core, but supports Dike-style integrations through:

- per-document-type `action_policy` / `action_policies` in profile YAML,
- policy reasons, source-system tags, evidence refs and references on `ReviewAction`,
- protected-pattern guards for corrected output safety,
- `ReviewContextProvider` for grounding, classifier results or external evidence,
- structural Dike adapters under `reviewkit.adapters.dike`.

## Contributors

- [mikolaj92](https://github.com/mikolaj92)
- [PSyron](https://github.com/PSyron)

## License

ReviewKit is released under the MIT License. See [LICENSE](LICENSE).
