# Contributing

Thanks for helping improve ReviewKit.

## Development

```bash
uv sync
uv run ruff check .
uv run mypy
uv run pytest
```

## Pull Requests

- Keep changes focused and covered by tests.
- Preserve the core contract: `reviewed.docx` marks every review action, while
  `corrected.docx` is a clean corrected document.
- Keep domain-specific legal logic outside the core package unless it is added as
  an optional adapter.
