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
- The only review is the stay-or-go walk of one DOCX: zdanie, akapit,
  rozdział, całość. Side effects are Word comments and tracked changes on
  that same file via Docxtor.
- Do not add a second review path.
