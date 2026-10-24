```
id: C21
status: done
depends_on: [B1]
```
# C21 · Disk changes and tracked files

**Goal:** when you change a file outside iterthink (Word, Excel, a CAD export,
the file manager), it gets a version too, and you decide which files are tracked.

**Spec sections:** Principles; Folder model (source files stay, moving files
between projects, untracked files); Storage: files are the truth; Review
screen (disk changes over SSE); Shared folders (watcher + rescan).

**Confirmed** by the human on 2026-10-23: *Decided for you* is settled.

## Scope
- `iterthink/services/disk_scan.py` — compare tracked files against `head()`, record versions
- `bridge_real` — run the scan on open, on a watchdog event, and every 60 s
- `iterthink/web/templates/project/_disk_changed.html` (new partial), SSE notice
- `tests/v2/services/test_disk_scan.py`
- `scripts/strict_paths.d/C21.txt`

## Out of scope
- Other machines' logs (C14). Importing DOCX/PDF into working copies (C24).

## Interface
```python
@dataclass(frozen=True)
class ScanResult:
    changed: tuple[str, ...]; added: tuple[str, ...]; removed: tuple[str, ...]
    version: str | None

def tracked(project_dir: Path, settings: Settings) -> list[str]: ...
def scan(project_dir: Path, snaps: Snapshots, *, machine: str, project: str) -> ScanResult: ...
```

## Decided for you
- A file changed on disk by someone other than iterthink is the user's own
  edit: one snapshot per scan, "changed on disk", `version` event with
  `kind: "disk_change"`, actor `user:<os user>`, input source `file`. It is
  not a proposal (D-011 applies: your own edit is your verdict).
- Open proposals whose files changed become `conflict` (B1 rule), and review
  shows a notice over SSE.
- A file removed on disk is recorded as removed (`kind: "disk_remove"`); a file
  appearing is added. A move between two projects is removed in one and added
  in the other with a `moved_from` reference when the sha256 matches.
- Tracking (settings key `tracking`, inherited): include all files except
  hidden ones and `.iterthink/`; `tracking.exclude` globs (default
  `["~$*", "*.tmp", "*.bak", "*.lock"]`); `tracking.max_file_mb` (default 200).
  Larger files are listed as untracked in the explorer, never copied into `versions/`.
- Scans debounce for 2 s after the last disk event so a program saving in
  several steps makes one version.

## Acceptance
- [x] `test_external_edit_becomes_version_with_disk_change_kind`
- [x] `test_external_edit_puts_open_proposal_in_conflict`
- [x] `test_removed_and_added_files_recorded`
- [x] `test_move_between_projects_references_source`
- [x] `test_excluded_and_oversized_files_not_tracked`
- [x] `test_burst_of_writes_makes_one_version`
- [x] `test_scan_twice_without_changes_is_noop`
