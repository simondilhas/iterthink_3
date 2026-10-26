"""Forks, cloud-sync copies, and a project seen in two folders."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from secrets import token_hex

from iterthink.persistence.snapshots import Snapshots, Version
from iterthink.services.bridge import Invalid
from iterthink.services.event_log import Event, append, read_all
from iterthink.services.projects import project_file, settings_of, write_yaml

_MARKERS = ("OneDrive", "Dropbox", "iCloud")
_WARNING = (
    "This folder is synced. Simultaneous edits of the same file on two machines "
    "can produce conflict copies."
)


def cloud_warning(path: Path) -> str:
    """A warning when the folder sits in a cloud-sync directory, else empty."""
    text = str(path)
    if any(marker in text for marker in _MARKERS):
        return _WARNING
    return ""


def conflict_copies(root: Path) -> list[str]:
    """Sync-client copies. Each one is its own candidate, not a silent replacement."""
    found: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or _hidden(path.relative_to(root)):
            continue
        if _copy_name(path.name):
            found.append(path.relative_to(root).as_posix())
    return found


def reconcile(root: Path) -> list[str]:
    """Write sibling edits that do not overlap. Return the paths that do."""
    snaps = Snapshots(root)
    tips = snaps.tips()
    if len(tips) < 2:
        return []
    base = _shared_parent(snaps, tips)
    conflicts: list[str] = []
    paths = {path for tip in tips for path in tip.paths}
    for path in sorted(paths):
        if _apply(root, snaps, tips, base, path):
            conflicts.append(path)
    return conflicts


def conflict_versions(root: Path) -> dict[str, tuple[str, ...]]:
    """Version ids that disagree on a path."""
    snaps = Snapshots(root)
    tips = snaps.tips()
    if len(tips) < 2:
        return {}
    base = _shared_parent(snaps, tips)
    found: dict[str, tuple[str, ...]] = {}
    paths = {path for tip in tips for path in tip.paths}
    for path in sorted(paths):
        choices = _choices(snaps, tips, base, path)
        if len(choices) > 1:
            found[path] = tuple(choices)
    return found


def note_verdict_conflicts(
    root: Path,
    machine: str,
    project: str,
    now: Callable[[], datetime],
) -> list[str]:
    """Log a conflict when two machines accepted different proposals for one path."""
    events = read_all(root)
    paths = _proposal_paths(events)
    accepted = _accepted(events, paths)
    already = _already_conflict(events)
    noted: list[str] = []
    for proposal_id in sorted(accepted):
        if proposal_id in already:
            continue
        append(
            root,
            machine=machine,
            actor="user:local",
            type="conflict",
            project=project,
            payload={"paths": sorted(paths.get(proposal_id, ())), "proposal": proposal_id},
            contract="1.0.8",
            now=now,
        )
        noted.append(proposal_id)
    return noted


def assign_copy_id(folder: Path) -> str:
    """Give a copied project its own id. The bytes of source files stay."""
    data = settings_of(folder)
    if not isinstance(data.get("id"), str):
        raise Invalid("that folder is not a project")
    new_id = f"p-{token_hex(4)}"
    data["id"] = new_id
    write_yaml(project_file(folder), data)
    return new_id


def _shared_parent(snaps: Snapshots, tips: list[Version]) -> str | None:
    parents = {snaps.parent_of(tip.id) for tip in tips}
    if len(parents) != 1:
        return None
    parent = parents.pop()
    return parent if isinstance(parent, str) else None


def _apply(
    root: Path,
    snaps: Snapshots,
    tips: list[Version],
    base: str | None,
    path: str,
) -> bool:
    choices = _choices(snaps, tips, base, path)
    if len(choices) > 1:
        return True
    if len(choices) != 1:
        return False
    data = next(iter(choices.values()))
    dest = root / path
    if dest.is_file() and dest.read_bytes() == data:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return False


def _choices(
    snaps: Snapshots, tips: list[Version], base: str | None, path: str
) -> dict[str, bytes]:
    base_bytes = snaps.file_at(base, path) if base else None
    found: dict[str, bytes] = {}
    for tip in tips:
        version = tip.id
        data = snaps.file_at(version, path)
        if data is not None and data != base_bytes:
            found[version] = data
    return found


def _proposal_paths(events: list[Event]) -> dict[str, tuple[str, ...]]:
    found: dict[str, tuple[str, ...]] = {}
    for event in events:
        if event.type != "proposal_created":
            continue
        payload = event.payload
        raw = payload.get("paths")
        paths = tuple(raw) if isinstance(raw, list) else ()
        found[str(payload.get("id", ""))] = tuple(str(path) for path in paths)
    return found


def _accepted(events: list[Event], paths: dict[str, tuple[str, ...]]) -> set[str]:
    by_path: dict[str, set[str]] = {}
    for event in events:
        if event.type != "verdict":
            continue
        payload = event.payload
        if payload.get("verdict") != "accepted":
            continue
        proposal_id = str(payload.get("proposal", ""))
        for path in paths.get(proposal_id, ()):
            by_path.setdefault(path, set()).add(proposal_id)
    crowded = {item for group in by_path.values() if len(group) > 1 for item in group}
    return crowded


def _already_conflict(events: list[Event]) -> set[str]:
    found: set[str] = set()
    for event in events:
        if event.type != "conflict":
            continue
        payload = event.payload
        proposal = payload.get("proposal")
        if isinstance(proposal, str):
            found.add(proposal)
    return found


def _copy_name(name: str) -> bool:
    return "conflicted copy" in name or "-PC-" in name


def _hidden(rel: Path) -> bool:
    return any(part.startswith(".") for part in rel.parts)
