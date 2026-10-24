"""Copy a project for archive or for a client who can verify the record."""

from __future__ import annotations

import csv
import json
import shutil
from collections.abc import Callable
from pathlib import Path

from iterthink.persistence.snapshots import SnapshotError, Snapshots
from iterthink.services.audit import export_audit, verdict_rows, verifier_bytes
from iterthink.services.bridge import HandoverMode, Invalid
from iterthink.services.event_log import LogCorrupt, read, read_all, utc_now

Emit = Callable[[Path, str, str, str, dict[str, object]], None]


def hand_over(
    root: Path,
    mode: HandoverMode,
    target: Path,
    machine: str,
    project: str,
    emit: Emit,
) -> Path:
    """Full copy plus the audit export, or a client bundle with a verification folder."""
    destination = _place(root, target)
    heads = _heads(root)
    snapshot = _snapshot(root)
    payload: dict[str, object] = {"heads": heads, "mode": mode, "snapshot": snapshot}
    emit(root, project, "user:local", "handover", payload)
    if mode == "full":
        export_audit(root, utc_now())
        shutil.copytree(root, destination, symlinks=True)
        return destination
    _copy_client(root, destination)
    _write_verification(root, destination / "verification", heads, snapshot)
    return destination


def _place(root: Path, target: Path) -> Path:
    destination = target.expanduser().resolve()
    source = root.resolve()
    if destination == source or source in destination.parents:
        raise Invalid("handover target is inside the project")
    if destination.exists():
        raise Invalid("handover target already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination


def _heads(root: Path) -> dict[str, dict[str, str | int]]:
    found: dict[str, dict[str, str | int]] = {}
    log_dir = root / ".iterthink" / "log"
    if not log_dir.is_dir():
        return found
    for path in sorted(log_dir.glob("*.jsonl")):
        if not path.is_file():
            continue
        try:
            events = list(read(path))
        except (LogCorrupt, OSError, ValueError):
            continue
        if not events:
            continue
        last = events[-1]
        found[path.stem] = {"hash": last.hash, "seq": last.seq}
    return found


def _snapshot(root: Path) -> str:
    try:
        return Snapshots(root).head().id
    except SnapshotError:
        return ""


def _wanted(relative: Path) -> bool:
    parts = relative.parts
    if not parts or parts[0] != ".iterthink":
        return bool(parts)
    return len(parts) > 1 and parts[1] == "exports"


def _copy_client(root: Path, destination: Path) -> None:
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if not _wanted(relative) or path.is_symlink():
            continue
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())


def _write_verification(
    root: Path, folder: Path, heads: dict[str, dict[str, str | int]], snapshot: str
) -> None:
    folder.mkdir(parents=True)
    (folder / "verify_log.py").write_bytes(verifier_bytes())
    manifest = {"heads": heads, "snapshot": snapshot}
    (folder / "heads.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (folder / "snapshot.txt").write_text(snapshot + "\n", encoding="utf-8")
    _write_verdicts(folder / "verdicts.csv", verdict_rows(root, read_all(root)))
    _copy_logs(root, folder)


def _write_verdicts(path: Path, rows: list[tuple[str, str, str, str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time", "who", "file", "verdict", "reason"])
        writer.writerows(rows)


def _copy_logs(root: Path, folder: Path) -> None:
    source = root / ".iterthink" / "log"
    target = folder / ".iterthink" / "log"
    target.mkdir(parents=True)
    if not source.is_dir():
        return
    for path in sorted(source.glob("*.jsonl")):
        if path.is_file():
            (target / path.name).write_bytes(path.read_bytes())
