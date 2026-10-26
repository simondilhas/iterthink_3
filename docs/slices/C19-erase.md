```
id: C19
status: done
depends_on: [C13]
```
# C19 · Erase

**Goal:** when content must really be removed (personal data, a wrong
upload), it disappears from history, and the log says that something was
erased, by whom and why, without containing it.

**Spec sections:** none yet. The spec (`docs/spec/`) has no Erase section; its Audit
trail says "Logs are never rewritten. Corrections are new events." This slice
does not rewrite the log, but deleting snapshot objects and blobs is a new
rule. **Set `ready`** by the human on 2026-10-23: deleting the snapshot objects
and blobs that only the erased version used is allowed; the log is never
rewritten. The Erase section in the spec is still to be written: propose its
text in the run report.

## Scope
- `persistence/snapshots.py` — delete object files that the erased version alone referenced. Do not call jj.
- `iterthink/services/erase.py`, `iterthink/web/routes/erase.py`
- `tests/v2/services/test_erase.py`
- `scripts/strict_paths.d/C19.txt`

## Decided for you
- Two-step confirmation in the UI, reason required, logged as `erase` audit
  event with file path hash, version ids and reason (no content).
- Blobs referenced only by erased events are deleted; events stay (hashes intact).
- Other machines see the erase event and drop the content on their next rescan.
- Anchors and handover bundles made before the erase still verify (the log
  chain is unchanged).

## Acceptance
- [x] `test_erased_content_unreachable_in_history`
- [x] `test_log_still_verifies_after_erase`
- [x] `test_erase_event_has_no_content`
- [x] `test_erase_requires_reason_and_confirmation`
