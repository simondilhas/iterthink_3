```
id: C14
status: done
depends_on: [C1, C22]
```
# C14 · Shared folders and several machines

**Goal:** several people open the same project on a NAS or synced folder
without a server, and nothing is silently lost.

**Spec sections:** Shared folders (network drives, NAS, synced folders);
Folder model (copy detection).

## Scope
- `iterthink/services/watcher.py`, `iterthink/services/sync_detect.py`
- `persistence/snapshots.py` — `head()` across machines (see below)
- `bridge_real` — other machines' events, copy question
- `iterthink/web/templates/project/` banner partials (new files only)
- `tests/v2/services/test_watcher.py`, `test_sync_detect.py`,
  `tests/v2/e2e/test_two_machines.py`
- `scripts/strict_paths.d/C14.txt`

## Out of scope
- Claim files themselves (C22). Edits made outside iterthink on this machine (C21).

## Decided for you
- No snapshot claim: the spec lets several machines work at once, and
  snapshots are content-addressed and written once. Each snapshot names its
  parent. When two machines' snapshots share a parent, `head()` is the one
  whose `version` event comes last in merge order `(ts, machine, seq)`, and
  for every file that both changed, review shows a conflict (two candidates),
  never a silent pick. Confirmed by the human on 2026-10-23.
- Other machines' logs tailed via watchdog plus a rescan every 60 s (network
  shares drop notifications). New events reach the index (C1) and the UI via SSE.
- Cloud-sync detection by path markers (OneDrive, Dropbox, iCloud) → banner
  warning that simultaneous edits of the same file on two machines produce
  sync-client conflict copies; such copies (`… (conflicted copy) …`,
  `…-PC-name.md`) are shown as separate candidates.
- Conflicting verdicts across machines surface in review (C1 conflict rows).
- Copy question when the same project id is seen at two existing paths:
  "Copy or same project?" — copy gets a new id, logged.
- Two-machine tests simulate machines with two `RealBridge` instances
  (different `machine`, `state_dir`) on one folder.

## Acceptance
- [x] `test_two_machines_edit_different_files_both_kept`
- [x] `test_two_machines_edit_same_file_shows_conflict`
- [x] `test_other_machine_events_appear_after_rescan`
- [x] `test_conflicting_verdicts_from_two_machines_in_review`
- [x] `test_cloud_sync_folder_warns_and_conflict_copy_is_candidate`
- [x] `test_confirmed_copy_gets_new_id`
