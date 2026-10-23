```
id: B1
status: ready
depends_on: [A2, A3, A4]
```
# B1 · Real bridge

**Goal:** the bridge runs on real version history, the decision log and the
diff engines, and passes the same contract tests as the fake.

**Spec sections:** Data model (Storage, Mapping of 2.0 concepts → proposal);
Source files stay (`versions/`); Folder model (project identity, copies);
Tasks and agents → Parallel work and conflicts.

**Direction:** history is A3's content-addressed snapshots
(`persistence/snapshots.py`). There is no jj, no `.jj/`, no `persistence/vcs.py`.

## Start
Work on the current branch. A2, A3 and A4 must be `done`.

## Scope
- `iterthink/services/bridge_real.py` — `RealBridge` implementing the first
  part of `Bridge` (projects, egress setting, files, read, save, history, diff,
  restore, propose, proposals, proposal_diff, accept, reject, log, verify,
  search). Later methods raise `NotImplementedError("slice Cn")` with the
  slice id from `docs/slices/README.md`.
- `iterthink/services/projects.py` — project identity, machine identity,
  opened-projects registry.
- `iterthink/services/proposals.py` — proposals on top of `Snapshots` and `event_log`.
- `tests/v2/services/test_projects.py`, `test_proposals.py`
- `scripts/strict_paths.d/B1.txt`

## Out of scope
- Index/FTS (C1; search scans files for now). Egress enforcement beyond
  storing the setting (C2). Edits made outside iterthink (C21). Claims (C22).
  Shared folders (C14). Re-running an agent on a newer version ("rebase", C8).

## Interface
```python
class RealBridge:  # implements iterthink.services.bridge.Bridge
    def __init__(self, state_dir: Path | None = None, machine: str | None = None,
                 now: Callable[[], datetime] = utc_now) -> None: ...

# proposals.py
@dataclass(frozen=True)
class Proposal:
    id: str; baseline: str; draft: str; paths: tuple[str, ...]
    actor: str; reason_ref: str; status: ProposalStatus

def create(project_dir: Path, snaps: Snapshots, *, machine: str, project: str,
           changes: Mapping[str, str], actor: str, reason: str,
           baseline: str | None) -> Proposal: ...
def load_all(project_dir: Path, snaps: Snapshots) -> list[Proposal]: ...  # from the log
def conflicts(proposal: Proposal, snaps: Snapshots, project_dir: Path) -> list[str]: ...
```

## Decided for you
- `state_dir` default: OS app dir (`~/.config/iterthink`, `~/Library/Application
  Support/iterthink`, `%APPDATA%\iterthink`). Holds `machine.yaml`
  (`id: m-<8 hex>`, created once) and `projects.json` (opened project paths).
- Project identity: `.iterthink/settings/project.yaml` with `id: p-<8 hex>`,
  `egress: shielded`. Same id at two existing paths → treat the one opened
  first as the project and record a `copy_suspected` event (UI for it in C14).
- Tracked files: every file under the project root except `.iterthink/`,
  hidden files and folders (name starts with `.`), and files over 200 MB.
  Provisional; C21 makes this a setting.
- `make_project`: write project.yaml, `Snapshots.init()`, first snapshot
  "started tracking", event `project_created`. On Windows set the hidden
  attribute on `.iterthink/` (spec Folder model).
- Every version-creating action: snapshot first, then `event_log.append`
  with `version` (the snapshot id) in the payload.
- Event types: `project_created`, `version` (own edit, as the user's verdict:
  payload `verdict: "accepted"`, `kind: "own_edit"`), `restore`,
  `proposal_created`, `verdict`, `conflict`, `settings`, `copy_suspected`,
  `checkpoint` (A2). Reasons and free text go to blobs.
- Proposals:
  - id `pr-<8 hex>`. `create` writes `Snapshots.draft(baseline, changes, …)`
    (baseline default: `head()`), then a `proposal_created` event with
    `id`, `baseline`, `draft`, `paths`, `actor`, reason blob.
  - Nothing lives outside the project except caches: status is rebuilt from
    `proposal_created`, `verdict` and `conflict` events, so it survives restarts
    and moves with the folder.
  - Conflict: a proposed path whose current bytes on disk differ from its
    bytes in `baseline`. `accept` on such a proposal raises `Conflict`, writes
    a `conflict` event and changes no file.
  - Accept: copy the draft's bytes onto the source files (temp file +
    `os.replace` per file), snapshot "accepted <reason>", `verdict` event with
    `verdict: "accepted"`. Then every other open proposal touching the same
    paths gets a `conflict` event right away, so review shows it as competing.
  - Reject: `verdict` event with `verdict: "rejected"` and the reason blob.
    Draft manifests stay (history of what was proposed).
- `restore`: `Snapshots.restore`, copy bytes onto the source file, `restore` event.
- `log()` merges all machine logs via `event_log.read_all`, newest first,
  summaries in plain words from event type + payload (+ blob text).
- `verify()` uses `verify_log.verify_all`; first failure reported.
- `diff` uses `compare.engines.diff` with bytes from `Snapshots.file_at` / disk.
- On close (`RealBridge.close()`, also at interpreter exit) write a
  `checkpoint` event per open project.
- `get_bridge()` now returns `RealBridge` by default (already coded in bridge.py).

## Acceptance
- [ ] All of `tests/v2/contract/` passes for `real`, no skips.
- [ ] `test_machine_id_created_once`
- [ ] `test_project_id_survives_move` — move the folder, open again, same id, same history
- [ ] `test_copy_is_detected_when_both_paths_exist`
- [ ] `test_restart_keeps_proposals_and_statuses` — new `RealBridge` on same state
- [ ] `test_proposal_status_moves_with_the_folder` — copy the folder elsewhere, statuses intact
- [ ] `test_every_version_has_a_log_event_with_version_id`
- [ ] `test_log_verifies_after_session_and_fails_after_tamper`
- [ ] `test_accepting_one_proposal_marks_competing_one_conflict`
- [ ] `test_hidden_and_large_files_are_not_tracked`
- [ ] `test_close_writes_checkpoint`
- [ ] `test_windows_hidden_attribute` — skips off Windows
