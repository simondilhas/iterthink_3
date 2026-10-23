```
id: A3
status: ready
depends_on: []
```
# A3 · Version history (snapshots)

**Goal:** a project folder gets versions, restore and proposal drafts, and the user's files stay untouched until a draft is applied.

**Spec sections:** Source files stay, iterthink files move (`versions/`); Storage: files are the truth. jj is under "Later (not 2.0)" — do not add it.

## Scope
- `iterthink/persistence/snapshots.py`
- `tests/v2/persistence/test_snapshots.py`
- `scripts/strict_paths.d/A3.txt`

## Out of scope
- The event log (A2). Applying a proposal as a verdict (B1). Erase (C19). Claims (C14).

## Interface
```python
@dataclass(frozen=True)
class Version:
    id: str                 # snapshot id, not a git or jj id
    timestamp: str
    author: str
    description: str
    paths: tuple[str, ...]  # project-relative, newest snapshot first in history()

class SnapshotError(Exception): ...

class Snapshots:
    def __init__(self, project_dir: Path) -> None: ...
    def init(self) -> None: ...
    def snapshot(self, files: dict[str, bytes], description: str, author: str) -> Version | None: ...
    def history(self, path: str | None = None) -> list[Version]: ...
    def file_at(self, version: str, path: str) -> bytes | None: ...
    def restore(self, version: str, paths: list[str], description: str, author: str) -> Version: ...
    def head(self) -> Version: ...
    def draft(self, baseline: str, changes: dict[str, bytes], description: str, author: str) -> Version: ...
    def read_draft(self, version: str) -> dict[str, bytes]: ...
```

## Decided for you
- Bytes live at `<project>/.iterthink/versions/objects/<sha256>`. Write to a temp name in that directory, fsync, then `os.replace`. The same bytes are stored once.
- A snapshot is `<project>/.iterthink/versions/snapshots/<id>.json`: canonical JSON, sorted keys, fields `id`, `ts`, `author`, `description`, `parent`, `files` (path → sha256). `id` is the sha256 of that JSON with `id` set to `""`.
- `init` creates the two directories. It does not create `.jj/`, `.git`, or `.gitignore`. Idempotent.
- `snapshot` stores each file, writes the manifest, returns the version. Identical to `head` → `None`.
- `draft` writes a manifest with `"draft": true` and does not copy bytes onto source files.
- `restore` writes a new snapshot whose listed paths come from the old version and whose other paths come from `head`. It does not itself write source files. B1 copies bytes onto source files when a proposal is accepted.
- Paths are POSIX, relative, and must stay inside the project. Reject `.iterthink/` and anything that escapes the root.
- No subprocess, no `jj`, no network.

## Acceptance
- [ ] `test_init_creates_versions_dirs_only` — no `.jj`, no `.git`, no `.gitignore`, sources unchanged
- [ ] `test_init_is_idempotent`
- [ ] `test_snapshot_returns_id_and_paths`, `test_snapshot_without_changes_returns_none`
- [ ] `test_object_is_content_addressed` — same bytes, one object file
- [ ] `test_object_write_is_atomic` — a crash mid-write leaves the previous object
- [ ] `test_large_file_is_stored` — 5 MB
- [ ] `test_history_newest_first`, `test_history_filtered_by_path`
- [ ] `test_file_at_returns_old_bytes_and_none_when_absent`
- [ ] `test_restore_creates_new_version_and_keeps_old`
- [ ] `test_draft_leaves_source_files_untouched`
- [ ] `test_paths_with_spaces_and_umlauts`
- [ ] `test_path_escape_raises`
