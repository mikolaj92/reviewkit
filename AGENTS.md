# Agent guidance

## Composition

Non-negotiable for this repo:

1. Prefer small Unix-style modules/processes and compose them.
2. Multi-step flows use Fala when orchestration is needed. Multiple Fala journals are OK.
3. Nested Fala is OK.
4. reviewkit stays the document-review rendering/engine concerns library used with Dike — do not grow into a product orchestrator or re-implement Argus/Temida flows.
5. Domain engines stay engines; composition happens at the host/Fala boundary, not via fat god-files.
