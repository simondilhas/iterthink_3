```
id: C11
status: done
depends_on: [C1, C2]
```
# C11 · Impact checks in review

**Goal:** when you review a change, iterthink tells you whether it matters and
what else it touches, with sources.

**Spec sections:** What stays → services/ (impact analysis runner, checks
runner); article §6 ("impact analysis is now one block among many").

## Scope
- `iterthink/services/impact_review.py` — wraps the 1.x impact runner for a proposal or version
- `iterthink/web/templates/review/impact.html` (new partial; A5 owns the folder)
- `iterthink/web/routes/impact.py`
- `tests/v2/services/test_impact_review.py`, `tests/v2/web/test_c11_impact.py`
- `scripts/strict_paths.d/C11.txt`

## Decided for you
- Runs on demand ("Check impact" button) and automatically for proposals
  touching files matched by `impact_checks.yaml`.
- Uses the existing checks and prompts (seed files unchanged).
- Calls go through egress (`purpose="impact"`); under `none` only local models.
- Context comes from `search.hybrid` (C1), scoped to this project only; the
  model call runs off the request thread and the result arrives over SSE.
- Result shown next to the diff: verdict suggestion, affected files with links,
  confidence. It is advice: it never accepts or rejects.
- Results cached per (proposal, check version).

## Acceptance
- [x] `test_impact_runs_on_proposal_and_lists_affected_files`
- [x] `test_impact_never_decides`
- [x] `test_impact_respects_egress_none`
- [x] `test_cached_result_reused`
