# Contributing

Thanks for helping improve ReviewKit.

## Development

```bash
uv sync --group dev
uv run ruff check .
uv run mypy
uv run pytest
```

## Pull Requests

- Keep changes focused and covered by tests.
- Preserve the core contract: `reviewed.docx` marks every review action, while
  `corrected.docx` is a clean corrected document.
- Keep domain data in a host Pack (ontology, units, rules), not in
  `src/reviewkit` and not in profile markdown as a Pack substitute.
- Do not import a model runtime into core. Hosts inject `DecisionClient` and
  `LLMClient`; tests use mocks.
