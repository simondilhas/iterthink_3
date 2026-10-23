"""Project identity, machine identity and which folders this machine has open."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

from iterthink.compare.engines import diff as diff_bytes
from iterthink.persistence.snapshots import SnapshotError, Snapshots, Version
from iterthink.services.bridge import (
    FileContent,
    FileDiff,
    FileEntry,
    Forbidden,
    Invalid,
    NotFound,
    SearchHit,
    VersionInfo,
    kind_of,
)
from iterthink.services.proposals import load_all

MAX_BYTES = 200 * 1024 * 1024
_OWN = {".iterthink", ".jj"}


def default_state_dir() -> Path:
    """OS config directory for this machine's iterthink state."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(base) / "iterthink"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "iterthink"
    config = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(config) / "iterthink"


def read_yaml(path: Path) -> dict[str, object]:
    """Load a mapping, or an empty one when the file is missing."""
    if not path.is_file():
        return {}
    loaded: object = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        return {}
    return {str(key): value for key, value in loaded.items()}


def write_yaml(path: Path, data: dict[str, object]) -> None:
    """Write a mapping. The parent directory is created when needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")


def hide_iterthink(root: Path) -> None:
    """Make `.iterthink` a hidden folder on Windows."""
    folder = root / ".iterthink"
    folder.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        return
    import ctypes

    ctypes.windll.kernel32.SetFileAttributesW(str(folder), 0x02)


def machine_id(state_dir: Path, explicit: str | None) -> str:
    """The id passed in, or the one stored in `machine.yaml`, created once."""
    if explicit:
        return explicit
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "machine.yaml"
    found = read_yaml(path).get("id")
    if isinstance(found, str) and found:
        return found
    from secrets import token_hex

    new = f"m-{token_hex(4)}"
    write_yaml(path, {"id": new})
    return new


def project_file(root: Path) -> Path:
    return root / ".iterthink" / "settings" / "project.yaml"


def settings_of(root: Path) -> dict[str, object]:
    return read_yaml(project_file(root))


def relative(path: str) -> str:
    """A project-relative POSIX path, or Forbidden."""
    if not path or "\\" in path or path.startswith("/") or ":" in path.split("/")[0]:
        raise Forbidden(f"path must be relative to the project: {path!r}")
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise Forbidden(f"path leaves the project: {path!r}")
    if parts[0] in _OWN:
        raise Forbidden(f"iterthink's own data is not a project file: {path!r}")
    return path


def inside(root: Path, rel: str) -> Path:
    """Resolve `rel` and refuse a path that escapes `root`."""
    full = (root / rel).resolve()
    if not full.is_relative_to(root.resolve()):
        raise Forbidden(f"path leaves the project: {rel!r}")
    return full


def _hidden(rel: Path) -> bool:
    return any(part.startswith(".") for part in rel.parts)


def write_bytes(path: Path, data: bytes) -> None:
    """Write `data` via a temp file in the same directory, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


_TEXT = {"markdown", "table", "text"}


def search_hits(root: Path, query: str, limit: int) -> list[SearchHit]:
    """Keyword hits in file names and text. Empty query returns nothing."""
    needle = query.strip().casefold()
    if not needle:
        return []
    hits: list[SearchHit] = []
    for rel, data in tracked_files(root).items():
        if needle in rel.casefold():
            hits.append(SearchHit(path=rel, line=0, snippet=rel))
        if kind_of(rel) not in _TEXT:
            continue
        try:
            lines = data.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        hits.extend(
            SearchHit(path=rel, line=number, snippet=line.strip()[:200])
            for number, line in enumerate(lines, 1)
            if needle in line.casefold()
        )
    return hits[:limit]


def tracked_files(root: Path) -> dict[str, bytes]:
    """Source bytes. Skips iterthink data, hidden names and files over 200 MB."""
    found: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _hidden(rel) or path.stat().st_size > MAX_BYTES:
            continue
        found[rel.as_posix()] = path.read_bytes()
    return found


def ensure_project(folder: Path) -> tuple[str, str | None]:
    """Write project settings and the first snapshot when the folder is new.

    Returns the project id and the first version id, or None when it already existed.
    """
    folder = folder.resolve()
    if not folder.is_dir():
        raise NotFound(f"no folder at {folder}")
    data = settings_of(folder)
    existing = data.get("id")
    if isinstance(existing, str) and existing:
        return existing, None
    from secrets import token_hex

    home = Path.home().resolve()
    if folder == home or folder in home.parents:
        raise Forbidden(f"{folder} is too broad for a project. Pick a folder inside it.")
    project = f"p-{token_hex(4)}"
    try:
        write_yaml(project_file(folder), {"id": project, "egress": "shielded"})
        hide_iterthink(folder)
        snaps = Snapshots(folder)
        snaps.init()
        version = snaps.snapshot(tracked_files(folder), "started tracking", "user:local")
    except PermissionError as exc:
        raise Forbidden(f"iterthink cannot write to {folder}.") from exc
    vid = version.id if version is not None else snaps.head().id
    return project, vid


def folder_entries(folder: Path) -> list[tuple[Path, str | None]]:
    """The folder itself when it is a project, otherwise its first-level subfolders."""
    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        raise NotFound(f"no folder at {folder}")
    own = settings_of(folder).get("id")
    if isinstance(own, str) and own:
        return [(folder, own)]
    children = [
        item for item in folder.iterdir() if item.is_dir() and not item.name.startswith(".")
    ]
    entries: list[tuple[Path, str | None]] = []
    for child in sorted(children):
        pid = settings_of(child).get("id")
        entries.append((child, pid if isinstance(pid, str) else None))
    return entries


class Registry:
    """Opened project paths for one machine. The file is `projects.json`."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.opened: list[tuple[str, Path]] = []
        path = state_dir / "projects.json"
        if not path.is_file():
            return
        raw: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return
        for item in raw:
            if not isinstance(item, dict):
                continue
            pid = item.get("id")
            folder = item.get("path")
            if isinstance(pid, str) and isinstance(folder, str):
                self.opened.append((pid, Path(folder)))

    def save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = [{"id": pid, "path": str(path)} for pid, path in self.opened]
        target = self.state_dir / "projects.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(target)

    def path_of(self, project: str) -> Path | None:
        for pid, path in self.opened:
            if pid == project:
                return path
        return None

    def place(self, project: str, folder: Path) -> str:
        """Remember `folder` for `project`. `copy` leaves the first path in place."""
        folder = folder.resolve()
        current = self.path_of(project)
        if current is None:
            self.opened.append((project, folder))
            self.save()
            return "added"
        if current.resolve() == folder:
            return "same"
        if current.exists() and folder.exists():
            return "copy"
        self.opened = [(pid, folder if pid == project else path) for pid, path in self.opened]
        self.save()
        return "moved"


_MISSING = object()


def _is_draft(root: Path, version: str) -> bool:
    path = root / ".iterthink" / "versions" / "snapshots" / f"{version}.json"
    if not path.is_file():
        return False
    loaded: object = json.loads(path.read_text(encoding="utf-8"))
    return isinstance(loaded, dict) and loaded.get("draft") is True


def shown(version: Version) -> VersionInfo:
    return VersionInfo(
        id=version.id,
        ts=version.timestamp,
        actor=version.author,
        message=version.description,
        paths=version.paths,
    )


def applied_versions(root: Path) -> list[Version]:
    """Snapshots that are not drafts, newest first."""
    return [item for item in Snapshots(root).history() if not _is_draft(root, item.id)]


def version_history(root: Path, path: str | None) -> list[VersionInfo]:
    rel = relative(path) if path else None
    versions = applied_versions(root)
    if rel is not None:
        versions = [item for item in versions if rel in item.paths]
    return [shown(item) for item in versions]


def store_edit(root: Path, path: str, text: str, actor: str, message: str) -> VersionInfo | None:
    """Write one text file and snapshot it. None when the bytes did not change."""
    rel = relative(path)
    full = inside(root, rel)
    if kind_of(rel) not in _TEXT or full.suffix.lower() == ".xlsx":
        raise Invalid(f"{rel} is not a text file; it can't be edited here")
    data = text.encode("utf-8")
    if full.is_file() and full.read_bytes() == data:
        return None
    write_bytes(full, data)
    version = Snapshots(root).snapshot(tracked_files(root), message or f"edited {rel}", actor)
    if version is None:
        return None
    return shown(version)


def file_entries(root: Path) -> list[FileEntry]:
    """Tracked files and how many open proposals touch each one."""
    counts: dict[str, int] = {}
    for item in load_all(root, Snapshots(root)):
        if item.status != "open":
            continue
        for path in item.paths:
            counts[path] = counts.get(path, 0) + 1
    return [
        FileEntry(
            path=path,
            kind=kind_of(path),
            size=len(data),
            open_proposals=counts.get(path, 0),
        )
        for path, data in tracked_files(root).items()
    ]


def read_content(root: Path, path: str) -> FileContent:
    rel = relative(path)
    full = inside(root, rel)
    if not full.is_file():
        raise NotFound(f"no file {path}")
    data = full.read_bytes()
    text = None
    if kind_of(rel) in _TEXT and full.suffix.lower() != ".xlsx":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = None
    return FileContent(path=rel, kind=kind_of(rel), size=len(data), text=text)


def _at(root: Path, version: str, rel: str) -> bytes | None:
    try:
        return Snapshots(root).file_at(version, rel)
    except SnapshotError as exc:
        raise NotFound(f"unknown version {version}") from exc


def _earlier(root: Path, rel: str, after: bytes | None) -> object:
    for version in applied_versions(root):
        data = Snapshots(root).file_at(version.id, rel)
        if data != after:
            return data
    return _MISSING


def compare_file(root: Path, path: str, base: str | None, target: str | None) -> FileDiff:
    rel = relative(path)
    if target is None:
        full = inside(root, rel)
        after = full.read_bytes() if full.is_file() else None
    else:
        after = _at(root, target, rel)
    before = _at(root, base, rel) if base else _earlier(root, rel, after)
    if isinstance(before, bytes) or before is None:
        return diff_bytes(rel, before, after)
    return FileDiff(path=rel, kind="none", summary="no earlier version differs")


def restore_file(root: Path, path: str, version: str, actor: str) -> VersionInfo:
    """New snapshot with `path` as it was, and those bytes written to the file."""
    rel = relative(path)
    data = _at(root, version, rel)
    if data is None:
        raise NotFound(f"{rel} did not exist in that version")
    try:
        made = Snapshots(root).restore(version, [rel], f"restored {rel}", actor)
    except SnapshotError as exc:
        raise NotFound(f"unknown version {version}") from exc
    write_bytes(inside(root, rel), data)
    return shown(made)
