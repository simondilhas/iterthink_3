"""Versions for files changed outside iterthink."""

from __future__ import annotations

import fnmatch
import getpass
import hashlib
import json
import os
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from iterthink.persistence.snapshots import SnapshotError, Snapshots
from iterthink.services.event_log import append, utc_now
from iterthink.services.projects import settings_of
from iterthink.services.proposals import CONTRACT, conflicts, load_all

DEBOUNCE_S = 2.0
_DEFAULT_EXCLUDE = ("~$*", "*.tmp", "*.bak", "*.lock")
_LISTENERS: dict[str, list[queue.Queue[ScanResult]]] = {}
_LISTEN_LOCK = threading.Lock()


@dataclass(frozen=True)
class Settings:
    """Which files a project tracks. Project yaml overrides these defaults."""

    exclude: tuple[str, ...] = _DEFAULT_EXCLUDE
    max_file_mb: int = 200


@dataclass(frozen=True)
class ScanResult:
    """What one scan found. ``version`` is set when a snapshot was stored."""

    changed: tuple[str, ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]
    version: str | None


class Debounce:
    """Run ``action`` once, ``wait`` seconds after the last ``push``."""

    def __init__(
        self,
        wait: float,
        action: Callable[[], None],
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._wait = wait
        self._action = action
        self._clock = clock or time.monotonic
        self._due: float | None = None

    def push(self) -> None:
        self._due = self._clock() + self._wait

    def poll(self) -> bool:
        if self._due is None or self._clock() < self._due:
            return False
        self._due = None
        self._action()
        return True


def load_settings(project_dir: Path) -> Settings:
    """Tracking rules from project settings, otherwise the defaults."""
    raw = settings_of(project_dir).get("tracking")
    if not isinstance(raw, dict):
        return Settings()
    exclude = raw.get("exclude", _DEFAULT_EXCLUDE)
    names = tuple(str(item) for item in exclude) if isinstance(exclude, list) else _DEFAULT_EXCLUDE
    max_mb = raw.get("max_file_mb", 200)
    if isinstance(max_mb, bool) or not isinstance(max_mb, int):
        max_mb = 200
    return Settings(exclude=names, max_file_mb=max_mb)


def _hidden(rel: str) -> bool:
    return any(part.startswith(".") for part in rel.split("/"))


def _excluded(name: str, settings: Settings) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in settings.exclude)


def tracked(project_dir: Path, settings: Settings) -> list[str]:
    """Project-relative paths that belong in a snapshot."""
    limit = settings.max_file_mb * 1024 * 1024
    found: list[str] = []
    for path in sorted(project_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(project_dir).as_posix()
        if _hidden(rel) or _excluded(path.name, settings):
            continue
        if path.stat().st_size > limit:
            continue
        found.append(rel)
    return found


def _read(project_dir: Path, paths: list[str]) -> dict[str, bytes]:
    return {rel: (project_dir / rel).read_bytes() for rel in paths}


def _head_bytes(snaps: Snapshots) -> dict[str, bytes]:
    try:
        version = snaps.head()
    except SnapshotError:
        return {}
    found: dict[str, bytes] = {}
    for path in version.paths:
        data = snaps.file_at(version.id, path)
        if data is not None:
            found[path] = data
    return found


def _diff(
    current: dict[str, bytes], previous: dict[str, bytes]
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    changed = tuple(
        sorted(path for path in current if path in previous and current[path] != previous[path])
    )
    added = tuple(sorted(path for path in current if path not in previous))
    removed = tuple(sorted(path for path in previous if path not in current))
    return changed, added, removed


def _actor() -> str:
    try:
        name = getpass.getuser()
    except OSError:
        name = "local"
    return f"user:{name or 'local'}"


def _manifests(folder: Path) -> list[dict[str, Any]]:
    directory = folder / ".iterthink" / "versions" / "snapshots"
    if not directory.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for path in directory.glob("*.json"):
        raw: object = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            found.append(raw)
    return found


def _head_files(manifests: list[dict[str, Any]]) -> dict[str, str]:
    applied = [item for item in manifests if item.get("draft") is not True]
    if not applied:
        return {}
    head = max(applied, key=lambda item: str(item.get("ts", "")))
    files = head.get("files")
    if not isinstance(files, dict):
        return {}
    return {str(path): str(digest) for path, digest in files.items()}


def _moved_from(project_dir: Path, digest: str) -> str | None:
    parent = project_dir.parent
    if not parent.is_dir():
        return None
    for sibling in sorted(parent.iterdir()):
        if sibling.resolve() == project_dir.resolve() or not sibling.is_dir():
            continue
        ref = _removed_match(sibling, digest)
        if ref:
            return ref
    return None


def _removed_match(folder: Path, digest: str) -> str | None:
    manifests = _manifests(folder)
    head = _head_files(manifests)
    if digest in head.values():
        return None
    project = settings_of(folder).get("id")
    label = project if isinstance(project, str) and project else folder.name
    for item in manifests:
        if item.get("draft") is True:
            continue
        files = item.get("files")
        if not isinstance(files, dict):
            continue
        for path, value in files.items():
            if str(value) == digest and str(path) not in head:
                return f"{label}/{path}"
    return None


def _sources(project_dir: Path, added: tuple[str, ...], current: dict[str, bytes]) -> list[str]:
    found: list[str] = []
    for path in added:
        ref = _moved_from(project_dir, hashlib.sha256(current[path]).hexdigest())
        if ref and ref not in found:
            found.append(ref)
    return found


def _event(
    project_dir: Path,
    *,
    machine: str,
    project: str,
    actor: str,
    kind: str,
    paths: tuple[str, ...],
    version: str,
    moved: list[str],
) -> None:
    payload: dict[str, object] = {
        "kind": kind,
        "path": paths[0] if paths else "",
        "paths": list(paths),
        "source": "file",
        "version": version,
    }
    if moved:
        payload["moved_from"] = moved
    append(
        project_dir,
        machine=machine,
        actor=actor,
        type="version",
        project=project,
        payload=payload,
        contract=CONTRACT,
        now=utc_now,
    )


def _conflicts(project_dir: Path, snaps: Snapshots, machine: str, project: str, actor: str) -> None:
    for item in load_all(project_dir, snaps):
        if item.status != "open":
            continue
        stale = conflicts(item, snaps, project_dir)
        if not stale:
            continue
        append(
            project_dir,
            machine=machine,
            actor=actor,
            type="conflict",
            project=project,
            payload={"paths": stale, "proposal": item.id},
            contract=CONTRACT,
            now=utc_now,
        )


def notice(result: ScanResult) -> str:
    """One sentence for the disk-change notice."""
    parts: list[str] = []
    arrived = result.changed + result.added
    if arrived:
        parts.append(f"Changed on disk: {', '.join(arrived)}")
    if result.removed:
        parts.append(f"Removed on disk: {', '.join(result.removed)}")
    return " ".join(parts)


def publish(project: str, result: ScanResult) -> None:
    """Hand a scan result to whoever is listening for this project."""
    with _LISTEN_LOCK:
        listeners = list(_LISTENERS.get(project, ()))
    for listener in listeners:
        listener.put(result)


def subscribe(project: str) -> queue.Queue[ScanResult]:
    """A queue that receives later scans for ``project``."""
    found: queue.Queue[ScanResult] = queue.Queue()
    with _LISTEN_LOCK:
        _LISTENERS.setdefault(project, []).append(found)
    return found


def scan(project_dir: Path, snaps: Snapshots, *, machine: str, project: str) -> ScanResult:
    """Compare the folder with the latest version. One snapshot per scan."""
    current = _read(project_dir, tracked(project_dir, load_settings(project_dir)))
    changed, added, removed = _diff(current, _head_bytes(snaps))
    if not changed and not added and not removed:
        return ScanResult((), (), (), None)
    actor = _actor()
    version = snaps.snapshot(current, "changed on disk", actor)
    if version is None:
        return ScanResult(changed, added, removed, None)
    moved = _sources(project_dir, added, current)
    if changed or added:
        _event(
            project_dir,
            machine=machine,
            project=project,
            actor=actor,
            kind="disk_change",
            paths=changed + added,
            version=version.id,
            moved=moved,
        )
    if removed:
        _event(
            project_dir,
            machine=machine,
            project=project,
            actor=actor,
            kind="disk_remove",
            paths=removed,
            version=version.id,
            moved=[],
        )
    _conflicts(project_dir, snaps, machine, project, actor)
    result = ScanResult(changed, added, removed, version.id)
    publish(project, result)
    return result


class _SkipIterthink(FileSystemEventHandler):
    def __init__(self, root: Path, poke: Callable[[], None]) -> None:
        self._root = root
        self._poke = poke

    def on_any_event(self, event: FileSystemEvent) -> None:
        if _outside(self._root, event.src_path):
            return
        self._poke()


def _outside(root: Path, src: str | bytes) -> bool:
    text = src.decode() if isinstance(src, bytes) else src
    try:
        rel = Path(text).resolve().relative_to(root.resolve())
    except ValueError:
        return True
    return bool(rel.parts) and rel.parts[0] == ".iterthink"


def _scan_open(
    opened: Callable[[], list[tuple[str, Path]]],
    scan_one: Callable[[Path, str], None],
) -> None:
    for project, folder in opened():
        if folder.is_dir():
            scan_one(folder, project)


def _watch_new(
    opened: Callable[[], list[tuple[str, Path]]],
    observers: dict[str, Any],
    poke: Callable[[], None],
) -> None:
    for _project, folder in opened():
        if not folder.is_dir():
            continue
        key = str(folder.resolve())
        if key in observers:
            continue
        observer = Observer()
        observer.schedule(_SkipIterthink(folder, poke), str(folder), recursive=True)
        observer.start()
        observers[key] = observer


def start_watching(
    opened: Callable[[], list[tuple[str, Path]]],
    scan_one: Callable[[Path, str], None],
) -> Callable[[], None]:
    """Watch opened projects and rescan every minute. No-op under pytest."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return lambda: None
    stop = threading.Event()
    observers: dict[str, Any] = {}
    waiting = Debounce(DEBOUNCE_S, lambda: _scan_open(opened, scan_one))

    def loop() -> None:
        full_at = time.monotonic() + 60
        while not stop.wait(0.2):
            _watch_new(opened, observers, waiting.push)
            waiting.poll()
            now = time.monotonic()
            if now >= full_at:
                full_at = now + 60
                _scan_open(opened, scan_one)
        for observer in observers.values():
            observer.stop()
            observer.join(timeout=2)

    threading.Thread(target=loop, name="iterthink-disk", daemon=True).start()
    return stop.set
