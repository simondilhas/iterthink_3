```
id: C17
status: ready
depends_on: [B1]
```
# C17 · 1.x importer

**Goal:** an existing iterthink 1.x store becomes 2.0 projects with their full
version history and decisions.

**Spec sections:** What stays → persistence (migration note); Repository
layout (`services/importer_1x.py`).

## Scope
- `iterthink/services/importer_1x.py`, CLI entry `python -m iterthink.services.importer_1x`
- `iterthink/web/routes/importer.py` (one page: pick store, preview, run)
- `tests/v2/services/test_importer_1x.py` (builds a small 1.x store with existing fixtures)
- `scripts/strict_paths.d/C17.txt`

## Decided for you
- Read-only on the 1.x store; never modifies it.
- Each 1.x content lineage → snapshots (`persistence/snapshots.py`) in
  original order, one per 1.x version, author and original time in the
  description; each followed by a `version` event. Each 1.x verdict /
  annotation → an event with `imported_from` and `original_ts` in the payload.
  The event's own `ts` is the import time, so the log stays in order and the
  chain verifies.
- Target: the 1.x project's folder if it still exists (made a project via
  `make_project`), otherwise a folder the user picks in the preview.
- Idempotent: running twice imports nothing new (import marker event).
- Preview shows counts per project before running.

## Acceptance
- [ ] `test_versions_imported_in_order_with_authors`
- [ ] `test_verdicts_become_events_and_log_verifies`
- [ ] `test_import_is_idempotent`
- [ ] `test_store_unchanged_after_import`
