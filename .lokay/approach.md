# Approach plan

<!-- lokay-approach source=deterministic repo=mikolaj92/reviewkit issue=197 -->

Repository: `mikolaj92/reviewkit`  
Issue: #197 — README wskazuje nieistniejące ścieżki docs Fala/Splot

## Goal

README: „takt README / docs/FALA_INTEGRATION.md, splot CONCEPTUAL_MODEL.md, Fala CYBERNETIC_MAPPING.md”.

## Files likely touched

- `README.md` — point sibling Fala/Splot/takt references at existing `docs/` paths
- `tests/test_framework_core.py` — regression that the README cites those paths

## Test plan

- `uv run pytest tests/test_framework_core.py::test_readme_points_at_existing_sibling_docs -q`

## Non-goals

- (none stated)

## Notes

- Trust intentional issue; this plan is evidence for later review, not a human gate.
- Coding agent may refine details but should stay on the stated goal and non-goals.
- Collector boundary: if implementation introduces unbounded collection, ship only a bounded collector patch that starts durably in the background after merge. The coding agent and mill must not populate data or wait for collection to finish.
