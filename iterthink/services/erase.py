"""Remove snapshot bytes. The decision record gains an erase event and is not rewritten."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol, cast

from iterthink.persistence.snapshots import Snapshots
from iterthink.services.bridge import Invalid, NotFound
from iterthink.services.event_log import LogCorrupt, read_all


class _Host(Protocol):
    def _root(self, project: str) -> Path: ...
    def _event(
        self, root: Path, project: str, actor: str, kind: str, payload: dict[str, object]
    ) -> None: ...


def _host(bridge: EraseBridge) -> _Host:
    return cast(_Host, bridge)


def erased_ids(root: Path) -> set[str]:
    """Version ids named by erase events. Empty when the log cannot be read."""
    try:
        events = read_all(root)
    except (LogCorrupt, OSError, ValueError):
        return set()
    found: set[str] = set()
    for event in events:
        if event.type != "erase":
            continue
        versions = event.payload.get("versions")
        if isinstance(versions, list):
            found.update(item for item in versions if isinstance(item, str))
    return found


def apply_erases(root: Path) -> None:
    """Delete bytes that an erase event already named. Safe to call twice."""
    ids = erased_ids(root)
    if not ids:
        return
    Snapshots(root).drop_unique(sorted(ids))
    _drop_blobs(root, ids)


class EraseBridge:
    """Real-bridge erase. Reason and confirmation are both required."""

    def erase(
        self, project: str, versions: list[str], reason: str, confirmed: bool, actor: str
    ) -> None:
        _require(confirmed, reason, versions)
        host = _host(self)
        root = host._root(project)
        paths = _paths(root, versions)
        payload = _payload(paths, versions, reason)
        Snapshots(root).drop_unique(sorted(set(versions)))
        host._event(root, project, actor, "erase", payload)
        _drop_blobs(root, set(versions))


def _require(confirmed: bool, reason: str, versions: list[str]) -> None:
    if not confirmed:
        raise Invalid("erase needs confirmation")
    if not reason.strip():
        raise Invalid("erase needs a reason")
    if not versions:
        raise Invalid("erase needs a version")


def _paths(root: Path, versions: list[str]) -> set[str]:
    listed = {item.id: item.paths for item in Snapshots(root).history()}
    missing = [version for version in versions if version not in listed]
    if missing:
        raise NotFound(f"unknown version {missing[0]}")
    found: set[str] = set()
    for version in versions:
        found.update(listed[version])
    return found


def _payload(paths: set[str], versions: list[str], reason: str) -> dict[str, object]:
    return {
        "path_hash": sorted(_path_hash(path) for path in paths),
        "reason": reason.strip(),
        "versions": sorted(set(versions)),
    }


def _path_hash(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()


def _drop_blobs(root: Path, ids: set[str]) -> None:
    try:
        events = read_all(root)
    except (LogCorrupt, OSError, ValueError):
        return
    erased: set[str] = set()
    kept: set[str] = set()
    for event in events:
        names = _blob_names(event.payload)
        if event.type == "erase" or _mentions(event.payload, ids):
            erased.update(names)
        else:
            kept.update(names)
    folder = root / ".iterthink" / "blobs"
    for name in erased - kept:
        path = folder / name
        if path.is_file():
            path.unlink()


def _mentions(payload: object, ids: set[str]) -> bool:
    return any(item in ids for item in _strings(payload))


def _blob_names(payload: object) -> set[str]:
    return {item[5:] for item in _strings(payload) if item.startswith("blob:") and len(item) == 69}


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        found: list[str] = []
        for item in value:
            found.extend(_strings(item))
        return found
    if isinstance(value, dict):
        found = []
        for item in value.values():
            found.extend(_strings(item))
        return found
    return []
