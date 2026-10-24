"""Verify the decision record when a project opens, and export it."""

from __future__ import annotations

import csv
import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from iterthink.services import verify_log
from iterthink.services.event_log import Event, LogCorrupt, read, read_all, read_blob
from iterthink.services.verify_log import verify

Emit = Callable[[Path, str, str, str, dict[str, object]], None]
_GUARD = threading.Lock()


@dataclass(frozen=True)
class Break:
    """One place where the decision record no longer checks."""

    machine: str
    line: int
    reason: str


def sentence(found: Break) -> str:
    """The banner sentence for a break."""
    return f"The decision record has a break at {found.machine} line {found.line}"


def verifier_bytes() -> bytes:
    """The stdlib verifier, copied into an export or a client bundle."""
    return Path(verify_log.__file__).read_bytes()


def verify_project(project_dir: Path) -> Break | None:
    """Every chain, then every checkpoint head. None when the record checks."""
    files = _logs(project_dir)
    for path in files:
        broken = _chain_break(path)
        if broken is not None:
            return broken
    logs = {path.stem: list(read(path)) for path in files}
    for path in files:
        broken = _checkpoint_break(path.stem, logs)
        if broken is not None:
            return broken
    return None


def publish_break(
    project_dir: Path,
    project: str,
    machine: str,
    actor: str,
    emit: Emit,
    *,
    background: bool = False,
) -> str:
    """Append one audit event for a new break. Returns the banner sentence."""
    if background and not os.environ.get("PYTEST_CURRENT_TEST"):
        threading.Thread(
            target=_publish,
            args=(project_dir, project, machine, actor, emit),
            name="iterthink-audit",
            daemon=True,
        ).start()
        return ""
    return _publish(project_dir, project, machine, actor, emit)


def export_audit(project_dir: Path, moment: datetime) -> Path:
    """CSV, JSON, the verifier and a verdict report under exports/audit-<date>/."""
    folder = _export_dir(project_dir, moment)
    events = read_all(project_dir)
    rows = [_row(project_dir, event) for event in events]
    text = json.dumps(rows, indent=2, ensure_ascii=False) + "\n"
    (folder / "events.json").write_text(text, encoding="utf-8")
    _write_events(folder / "events.csv", rows)
    (folder / "report.md").write_text(_report(project_dir, events), encoding="utf-8")
    (folder / "verify_log.py").write_bytes(verifier_bytes())
    return folder


def _logs(project_dir: Path) -> list[Path]:
    log_dir = project_dir / ".iterthink" / "log"
    if not log_dir.is_dir():
        return []
    return sorted(path for path in log_dir.glob("*.jsonl") if path.is_file())


def _chain_break(path: Path) -> Break | None:
    result = verify(path)
    if result.ok:
        return None
    return Break(path.stem, result.error_line or 0, result.reason)


def _checkpoint_break(machine: str, logs: dict[str, list[Event]]) -> Break | None:
    for index, event in enumerate(logs.get(machine, []), start=1):
        if event.type != "checkpoint":
            continue
        reason = _head_reason(event.payload.get("heads"), logs)
        if reason is not None:
            return Break(machine, index, reason)
    return None


def _head_reason(heads: object, logs: dict[str, list[Event]]) -> str | None:
    if not isinstance(heads, dict):
        return "checkpoint heads missing"
    for name, head in heads.items():
        if not isinstance(name, str) or not isinstance(head, dict):
            return "checkpoint head missing"
        digest = head.get("hash")
        if not isinstance(digest, str):
            return "checkpoint head missing"
        if not any(item.hash == digest for item in logs.get(name, [])):
            return "checkpoint head missing"
    return None


def _publish(project_dir: Path, project: str, machine: str, actor: str, emit: Emit) -> str:
    with _GUARD:
        found = verify_project(project_dir)
        if found is None:
            return ""
        if not _already(project_dir, machine, found):
            _emit(project_dir, project, actor, emit, found)
        return sentence(found)


def _already(project_dir: Path, machine: str, found: Break) -> bool:
    path = project_dir / ".iterthink" / "log" / f"{machine}.jsonl"
    try:
        events = list(read(path))
    except (LogCorrupt, OSError):
        return False
    return any(_same(event, found) for event in events)


def _same(event: Event, found: Break) -> bool:
    payload = event.payload
    return (
        event.type == "audit"
        and payload.get("machine") == found.machine
        and payload.get("line") == found.line
    )


def _emit(project_dir: Path, project: str, actor: str, emit: Emit, found: Break) -> None:
    payload: dict[str, object] = {
        "line": found.line,
        "machine": found.machine,
        "reason": found.reason,
    }
    try:
        emit(project_dir, project, actor, "audit", payload)
    except LogCorrupt:
        return


def _export_dir(project_dir: Path, moment: datetime) -> Path:
    stamp = moment.strftime("%Y-%m-%d")
    folder = project_dir / ".iterthink" / "exports" / f"audit-{stamp}"
    if folder.exists():
        stamp = moment.strftime("%Y-%m-%dT%H%M%SZ")
        folder = project_dir / ".iterthink" / "exports" / f"audit-{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _resolved(project_dir: Path, value: object) -> object:
    if isinstance(value, str) and value.startswith("blob:"):
        try:
            return read_blob(project_dir, value)
        except (OSError, ValueError):
            return value
    if isinstance(value, list):
        return [_resolved(project_dir, item) for item in value]
    if isinstance(value, dict):
        return {str(key): _resolved(project_dir, item) for key, item in value.items()}
    return value


def _row(project_dir: Path, event: Event) -> dict[str, object]:
    return {
        "actor": event.actor,
        "hash": event.hash,
        "machine": event.machine,
        "payload": _resolved(project_dir, event.payload),
        "seq": event.seq,
        "ts": event.ts,
        "type": event.type,
    }


def _write_events(path: Path, rows: list[dict[str, object]]) -> None:
    fields = ["seq", "time", "machine", "who", "type", "payload"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            payload = json.dumps(row["payload"], ensure_ascii=False, sort_keys=True)
            writer.writerow(
                {
                    "seq": row["seq"],
                    "time": row["ts"],
                    "machine": row["machine"],
                    "who": row["actor"],
                    "type": row["type"],
                    "payload": payload,
                }
            )


def _report(project_dir: Path, events: list[Event]) -> str:
    lines = [
        "# Decision record",
        "",
        "This record is tamper-evident. A change to a past line stays visible.",
        "",
    ]
    grouped: dict[str, list[str]] = {}
    for time, who, path, verdict, reason in verdict_rows(project_dir, events):
        grouped.setdefault(path, []).append(f"- {time} · {who} · {verdict} · {reason}")
    if not grouped:
        lines.extend(["No verdicts yet.", ""])
    for path in sorted(grouped):
        lines.extend([f"## {path or '(no file)'}", "", *grouped[path], ""])
    return "\n".join(lines)


def verdict_rows(project_dir: Path, events: list[Event]) -> list[tuple[str, str, str, str, str]]:
    """One row per file a verdict touched: time, who, file, verdict, reason."""
    paths: dict[str, list[str]] = {}
    rows: list[tuple[str, str, str, str, str]] = []
    for event in events:
        _remember_paths(paths, event)
        if event.type != "verdict":
            continue
        reason = _resolved(project_dir, event.payload.get("reason"))
        text = reason if isinstance(reason, str) else ""
        verdict = str(event.payload.get("verdict") or "")
        files = _files_for(paths, event.payload.get("proposal"))
        rows.extend((event.ts, event.actor, path, verdict, text) for path in files)
    return rows


def _remember_paths(paths: dict[str, list[str]], event: Event) -> None:
    if event.type != "proposal_created":
        return
    pid = event.payload.get("id")
    raw = event.payload.get("paths")
    if isinstance(pid, str) and isinstance(raw, list):
        paths[pid] = [item for item in raw if isinstance(item, str)]


def _files_for(paths: dict[str, list[str]], proposal: object) -> list[str]:
    if isinstance(proposal, str) and paths.get(proposal):
        return paths[proposal]
    return [""]
