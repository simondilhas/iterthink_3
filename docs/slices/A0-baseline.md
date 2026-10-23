```
id: A0
status: done
depends_on: []
```
# A0 · Baseline

**Goal:** `scripts/check.py --full` is green, so every later red is caused by
the change under review. This tree has no Flet app and no 1.x test suite.
Record violations in the copied core. Do not copy `studio/` back in.

**Spec sections:** Tech stack → Quality; What changes.

## Scope
- `tests/v2/architecture/allowlists.py` — record today's violations.
- `tests/legacy_known_failures.txt` — record today's failing 1.x tests.
- `scripts/strict_paths.d/A0.txt` — empty (comment only).

## Out of scope
- Fixing any violation or failing test. `pyproject.toml` (merged by hand this morning).

## Decided for you
- This slice is the one exception to "allowlists only shrink": add an entry
  for every current violation, commented with the slice that removes it
  (`"C18"` for Flet, `"unassigned"` if none fits).
- Failing 1.x tests: don't fix. Add `<node id>  # <one-line reason>` to
  `tests/legacy_known_failures.txt`. Tests needing a display, Ollama or the
  network count as failing if they fail here.
- If a dependency fails to install, record the last 20 lines under Blocked and stop.
- jj is not part of 2.0 (D-003, rejected). Do not install it. Tests marked
  `jj` are deselected; list them in the run report.

## Acceptance
- [x] `uv run python scripts/check.py --full` green without jj installed.
- [x] Run report: tests passing / deselected, with reasons grouped.
- [x] Every allowlist entry names its removing slice.
- [x] `test_allowlist_entries_are_still_needed` passes.
