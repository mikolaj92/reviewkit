# Approach plan

<!-- lokay-approach source=deterministic repo=mikolaj92/reviewkit issue=324 -->

Repository: `mikolaj92/reviewkit`  
Issue: #324 — Cleanup: wyrównaj docs do pinu takt v0.3.2

## Goal

README.md and src/reviewkit/homeostat.py match pyproject.toml’s `takt @ …@v0.3.2`.

## Files likely touched

- `src/reviewkit/homeostat.py`
- `tests/test_takt_integration.py`

## Test plan

- All user-facing takt version mentions say v0.3.2 (or “see pyproject.toml”)
- homeostat.py module docstring updated
- No accidental downgrade of the git pin
- `rg -n '0\.3\.1' README.md src/reviewkit` → empty (unless quoting historical changelog)
- `uv run pytest -q tests/test_takt_integration.py` (if environment allows)

## Non-goals

- Takt API migrations; Mojo install docs beyond the version string.

## Notes

- Trust intentional issue; this plan is evidence for later review, not a human gate.
- Coding agent may refine details but should stay on the stated goal and non-goals.
- Collector boundary: if implementation introduces unbounded collection, ship only a bounded collector patch that starts durably in the background after merge. The coding agent and lokay must not populate data or wait for collection to finish.
