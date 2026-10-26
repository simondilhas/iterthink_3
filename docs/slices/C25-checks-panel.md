```
id: C25
status: done
depends_on: [C1, C2]
```
# C25 · Checks panel

**Goal:** run the project's checks (`checks.yaml`) on a document or plan and
see the results as symbols next to the content, with sources.

**Spec sections:** Build order step 5 (checks); What stays → services/
(checks runner); View components (`<check-symbols>`); Ad-hoc apps →
Building blocks (Judge: `runCheck`).

**Confirmed** by the human on 2026-10-23: *Decided for you* is settled.

## Scope
- `iterthink/services/checks_review.py` — wraps the existing `checks_runner`
- `iterthink/web/routes/checks.py`, `templates/checks/`, `static/js/check-symbols.js`,
  `static/css/c25-checks.css`
- `tests/v2/services/test_checks_review.py`, `tests/v2/web/test_c25_checks.py`
- `scripts/strict_paths.d/C25.txt`

## Out of scope
- Impact checks on proposals (C11). Editing `checks.yaml` (C15).

## Decided for you
- A panel (Mod+Shift+C), closed by default, lists the checks from
  `checks.yaml` (inherited); "Run" on one or all, for the open file.
- Runs off the request thread through `llm_router` with
  `egress.check(..., "impact", tier)`; context from `search.hybrid` (C1);
  results stream over SSE.
- Results are advice: a symbol per paragraph / page region with the finding
  and sources; they never change a file or give a verdict.
- Each run is an audit event (check id, prompt version, model); results are
  cached per (file version, check version).

## Acceptance
- [x] `test_checks_listed_from_inherited_checks_yaml`
- [x] `test_run_streams_results_and_changes_nothing`
- [x] `test_check_respects_egress_none`
- [x] `test_cached_result_reused_for_same_version`
- [x] `test_panel_closed_by_default`
