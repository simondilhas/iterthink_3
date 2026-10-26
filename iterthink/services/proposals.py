"""Proposals stored as snapshot drafts and rebuilt from the event log."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from iterthink.compare.engines import diff as diff_bytes
from iterthink.persistence.snapshots import SnapshotError, Snapshots
from iterthink.services.bridge import (
    AppInfo,
    ChatInfo,
    ChatMessage,
    ExportInfo,
    FileDiff,
    HandoverMode,
    Intent,
    Invalid,
    NotFound,
    ProposalInfo,
    ProposalStatus,
    SettingInfo,
    TaskInfo,
)
from iterthink.services.event_log import Event, append, read_all, read_blob, store_blob

CONTRACT = "1.0.8"


@dataclass(frozen=True)
class Proposal:
    """One proposal. Status comes from the log, not from a side file."""

    id: str
    baseline: str
    draft: str
    paths: tuple[str, ...]
    actor: str
    reason_ref: str
    status: ProposalStatus
    created: str
    decided_by: str | None = None
    verdicts: Mapping[str, str] = field(default_factory=dict)  # change id → accepted|rejected


def describe(root: Path, event_type: str, payload: Mapping[str, object]) -> str:
    """One plain sentence for a log line."""
    if event_type == "project_created":
        return f"started tracking {payload.get('name', '')}".strip()
    if event_type == "version":
        return f"edited {payload.get('path', '')}".strip()
    if event_type == "restore":
        return f"restored {payload.get('path', '')}"
    if event_type == "proposal_created":
        paths = payload.get("paths")
        listed = ", ".join(paths) if isinstance(paths, list) else ""
        return f"proposed changes to {listed}: {reason_text(root, payload.get('reason'))}"
    if event_type == "verdict":
        word = "accepted" if payload.get("verdict") == "accepted" else "rejected"
        detail = reason_text(root, payload.get("reason"))
        return f"{word} proposal {payload.get('proposal')}: {detail}"
    if event_type == "change_verdict":
        word = "accepted" if payload.get("verdict") == "accepted" else "rejected"
        return f"{word} one change of proposal {payload.get('proposal')}"
    if event_type == "change_edit":
        return f"edited one change of proposal {payload.get('proposal')}"
    if event_type == "conflict":
        paths = payload.get("paths")
        listed = ", ".join(paths) if isinstance(paths, list) else ""
        return f"proposal {payload.get('proposal')} conflicts with later changes to {listed}"
    if event_type == "settings":
        return f"content may leave this machine: {payload.get('egress')}"
    if event_type == "copy_suspected":
        return f"this folder also exists at {payload.get('path')}"
    if event_type == "checkpoint":
        return "recorded the other logs"
    return event_type


def reason_text(root: Path, ref: object) -> str:
    """Blob text, or an empty string when the ref is not a blob."""
    if not isinstance(ref, str) or not ref.startswith("blob:"):
        return ""
    try:
        return read_blob(root, ref)
    except OSError:
        return ""


def create(
    project_dir: Path,
    snaps: Snapshots,
    *,
    machine: str,
    project: str,
    changes: Mapping[str, str],
    actor: str,
    reason: str,
    baseline: str | None,
    now: Callable[[], datetime],
) -> Proposal:
    """Store a draft and append `proposal_created`. Source files stay put."""
    if not reason.strip():
        raise Invalid("a proposal needs a reason")
    if not changes:
        raise Invalid("a proposal needs at least one change")
    baseline_id = baseline or snaps.head().id
    encoded = {path: text.encode("utf-8") for path, text in changes.items()}
    drafted = snaps.draft(baseline_id, encoded, f"proposed {reason}", actor)
    ref = store_blob(project_dir, reason)
    pid = f"pr-{secrets.token_hex(4)}"
    paths = tuple(sorted(changes))
    event = append(
        project_dir,
        machine=machine,
        actor=actor,
        type="proposal_created",
        project=project,
        payload={
            "actor": actor,
            "baseline": baseline_id,
            "draft": drafted.id,
            "id": pid,
            "paths": list(paths),
            "reason": ref,
        },
        contract=CONTRACT,
        now=now,
    )
    return Proposal(
        id=pid,
        baseline=baseline_id,
        draft=drafted.id,
        paths=paths,
        actor=actor,
        reason_ref=ref,
        status="open",
        created=event.ts,
    )


def _status_of(payload: Mapping[str, object]) -> ProposalStatus | None:
    verdict = payload.get("verdict")
    if verdict == "accepted":
        return "accepted"
    if verdict == "rejected":
        return "rejected"
    return None


def _apply(records: dict[str, dict[str, object]], event: Event) -> None:
    payload = event.payload
    if event.type == "verdict" and "proposal" in payload:
        pid = str(payload["proposal"])
        status = _status_of(payload)
        if pid in records and records[pid]["status"] == "open" and status is not None:
            records[pid]["status"] = status
            records[pid]["decided_by"] = event.actor
    elif event.type == "conflict":
        pid = str(payload.get("proposal", ""))
        if pid in records and records[pid]["status"] in {"open", "accepted"}:
            records[pid]["status"] = "conflict"
            records[pid]["decided_by"] = event.actor
    elif event.type in ("change_verdict", "change_edit"):
        _apply_change(records.get(str(payload.get("proposal", ""))), event)


def _apply_change(record: dict[str, object] | None, event: Event) -> None:
    if record is None or record["status"] != "open":
        return
    verdicts = record["verdicts"]
    change = str(event.payload.get("change", ""))
    if not isinstance(verdicts, dict):
        return
    if event.type == "change_edit":
        record["draft"] = str(event.payload.get("draft", record["draft"]))
        verdicts.pop(change, None)
    elif event.payload.get("verdict") in ("accepted", "rejected"):
        verdicts[change] = str(event.payload["verdict"])


def _record(root: Path, item: dict[str, object]) -> Proposal:
    paths = item["paths"]
    path_tuple = tuple(paths) if isinstance(paths, tuple) else ()
    status = item["status"]
    decided = item["decided_by"]
    verdicts = item.get("verdicts")
    return Proposal(
        id=str(item["id"]),
        baseline=str(item["baseline"]),
        draft=str(item["draft"]),
        paths=path_tuple,
        actor=str(item["actor"]),
        reason_ref=str(item["reason_ref"]),
        status=status if status in {"open", "accepted", "rejected", "conflict"} else "open",
        created=str(item["created"]),
        decided_by=decided if isinstance(decided, str) else None,
        verdicts=dict(verdicts) if isinstance(verdicts, dict) else {},
    )


def load_all(project_dir: Path, snaps: Snapshots) -> list[Proposal]:
    """Rebuild every proposal from `proposal_created`, `verdict`, `conflict` and the
    per-change `change_verdict` and `change_edit` events."""
    try:
        snaps.head()
    except SnapshotError:
        return []
    records: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for event in read_all(project_dir):
        if event.type == "proposal_created":
            pid = str(event.payload.get("id", ""))
            raw_paths = event.payload.get("paths")
            paths = tuple(raw_paths) if isinstance(raw_paths, list) else ()
            records[pid] = {
                "id": pid,
                "baseline": str(event.payload.get("baseline", "")),
                "draft": str(event.payload.get("draft", "")),
                "paths": paths,
                "actor": str(event.payload.get("actor", event.actor)),
                "reason_ref": str(event.payload.get("reason", "")),
                "status": "open",
                "created": event.ts,
                "decided_by": None,
                "verdicts": {},
            }
            order.append(pid)
        else:
            _apply(records, event)
    return [_record(project_dir, records[pid]) for pid in order]


def require(project_dir: Path, snaps: Snapshots, proposal_id: str) -> Proposal:
    """The proposal, or NotFound."""
    found = next((item for item in load_all(project_dir, snaps) if item.id == proposal_id), None)
    if found is None:
        raise NotFound(f"unknown proposal {proposal_id}")
    return found


def diff_files(project_dir: Path, proposal_id: str) -> list[FileDiff]:
    """Diff each proposed path against its baseline bytes."""
    snaps = Snapshots(project_dir)
    found = require(project_dir, snaps, proposal_id)
    try:
        drafted = snaps.read_draft(found.draft)
    except SnapshotError as exc:
        raise NotFound(f"unknown proposal {proposal_id}") from exc
    diffs: list[FileDiff] = []
    for rel in found.paths:
        try:
            before = snaps.file_at(found.baseline, rel)
        except SnapshotError:
            before = None
        diffs.append(diff_bytes(rel, before, drafted.get(rel)))
    return diffs


class Later:
    """Bridge methods that belong to a later slice. They refuse until that slice."""

    def interpret(self, project: str, line: str) -> Intent:
        raise NotImplementedError("slice C3")

    def chat_start(self, project: str, text: str, actor: str) -> ChatInfo:
        raise NotImplementedError("slice C5")

    def chat_send(self, project: str, chat_id: str, text: str, actor: str) -> Iterator[str]:
        raise NotImplementedError("slice C5")

    def chat_messages(self, project: str, chat_id: str) -> list[ChatMessage]:
        raise NotImplementedError("slice C5")

    def chats(self, project: str) -> list[ChatInfo]:
        raise NotImplementedError("slice C5")

    def app_build(self, project: str, request: str, actor: str) -> AppInfo:
        raise NotImplementedError("slice C6")

    def app_run(self, project: str, app_id: str) -> AppInfo:
        raise NotImplementedError("slice C6")

    def app_keep(self, project: str, app_id: str, actor: str) -> AppInfo:
        raise NotImplementedError("slice C6")

    def app_discard(self, project: str, app_id: str, actor: str) -> AppInfo:
        raise NotImplementedError("slice C6")

    def apps(self, project: str) -> list[AppInfo]:
        raise NotImplementedError("slice C6")

    def task_create(
        self, project: str, title: str, body: str, actor: str, depends_on: tuple[str, ...] = ()
    ) -> TaskInfo:
        raise NotImplementedError("slice C8")

    def task_start(self, project: str, task_id: str, actor: str) -> TaskInfo:
        raise NotImplementedError("slice C8")

    def tasks(self, project: str) -> list[TaskInfo]:
        raise NotImplementedError("slice C8")

    def export(
        self, project: str, path: str, format: str, template: str | None = None
    ) -> ExportInfo:
        raise NotImplementedError("slice C12")

    def import_returned(
        self, project: str, returned: Path, source: str, actor: str
    ) -> ProposalInfo:
        raise NotImplementedError("slice C12")

    def handover(self, project: str, mode: HandoverMode, target: Path) -> Path:
        raise NotImplementedError("slice C13")

    def settings(self, project: str) -> list[SettingInfo]:
        raise NotImplementedError("slice C15")


def compete(
    root: Path,
    snaps: Snapshots,
    project: str,
    proposal_id: str,
    paths: tuple[str, ...],
    actor: str,
    emit: Callable[[Path, str, str, str, dict[str, object]], None],
) -> None:
    """Mark another open proposal only when this accept changed its baseline."""
    for item in load_all(root, snaps):
        if item.id == proposal_id or item.status != "open":
            continue
        if not set(item.paths) & set(paths):
            continue
        stale = conflicts(item, snaps, root)
        if stale:
            emit(root, project, actor, "conflict", {"paths": stale, "proposal": item.id})


def conflicts(proposal: Proposal, snaps: Snapshots, project_dir: Path) -> list[str]:
    """Paths whose bytes on disk differ from the proposal's baseline."""
    stale: list[str] = []
    for path in proposal.paths:
        try:
            before = snaps.file_at(proposal.baseline, path)
        except SnapshotError:
            before = None
        full = project_dir / path
        current = full.read_bytes() if full.is_file() else None
        if current != before:
            stale.append(path)
    return stale
