"""Real bridge. Versions are snapshots. The log is the decision record."""

from __future__ import annotations

import atexit
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import cast

from iterthink.persistence.snapshots import SnapshotError, Snapshots
from iterthink.services.audit import publish_break
from iterthink.services.bridge import (
    BridgeError,
    Conflict,
    Egress,
    FileContent,
    FileDiff,
    FileEntry,
    HandoverMode,
    Invalid,
    LogEntry,
    NotFound,
    ProjectInfo,
    ProposalInfo,
    ProposalStatus,
    SearchHit,
    VerifyInfo,
    VersionInfo,
    kind_of,
)
from iterthink.services.chats import ChatsBridge
from iterthink.services.disk_scan import notice, scan, start_watching, subscribe
from iterthink.services.documents import DocumentsBridge
from iterthink.services.egress import apply_setting
from iterthink.services.egress import shield_text as shield_outbound
from iterthink.services.event_log import LogCorrupt, append, checkpoint, read_all, store_blob
from iterthink.services.event_log import utc_now as event_now
from iterthink.services.handover import hand_over
from iterthink.services.impact_review import ImpactBridge
from iterthink.services.indexer import schedule_index
from iterthink.services.intent import IntentBridge
from iterthink.services.projects import (
    Registry,
    compare_file,
    default_state_dir,
    file_entries,
    inside,
    machine_id,
    read_content,
    relative,
    restore_file,
    settings_of,
    shown,
    store_edit,
    tracked_files,
    version_history,
    write_bytes,
)
from iterthink.services.proposals import (
    CONTRACT,
    Later,
    Proposal,
    conflicts,
    create,
    diff_files,
    load_all,
    reason_text,
    require,
)
from iterthink.services.search import indexed_log, indexed_search
from iterthink.services.verify_log import verify_all
from iterthink.services.workspaces import WorkspacesBridge

_TEXT = {"markdown", "table", "text"}


def _info_of(root: Path, item: Proposal) -> ProposalInfo:
    return ProposalInfo(
        id=item.id,
        baseline=item.baseline,
        actor=item.actor,
        reason=reason_text(root, item.reason_ref),
        paths=item.paths,
        status=item.status,
        created=item.created,
        decided_by=item.decided_by,
    )


class RealBridge(IntentBridge, WorkspacesBridge, DocumentsBridge, ChatsBridge, ImpactBridge, Later):
    def __init__(
        self,
        state_dir: Path | None = None,
        machine: str | None = None,
        now: Callable[[], datetime] = event_now,
    ) -> None:
        self.state_dir = (state_dir or default_state_dir()).expanduser()
        self.machine = machine_id(self.state_dir, machine)
        self._now = now
        self._registry = Registry(self.state_dir)
        self._closed = False
        self._stop_watch = start_watching(self._opened, self._scan_one)
        atexit.register(self.close)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_watch()
        for project, folder in self._registry.opened:
            self._checkpoint(folder, project)

    def _checkpoint(self, folder: Path, project: str) -> None:
        if not folder.is_dir():
            return
        try:
            checkpoint(
                folder,
                machine=self.machine,
                actor="user:local",
                project=project,
                contract=CONTRACT,
                now=self._now,
            )
        except (OSError, LogCorrupt, BridgeError):
            return

    def _opened(self) -> list[tuple[str, Path]]:
        return list(self._registry.opened)

    def _scan_one(self, folder: Path, project: str) -> None:
        try:
            scan(folder, Snapshots(folder), machine=self.machine, project=project)
        except (OSError, SnapshotError, BridgeError):
            return

    def _check(self, folder: Path, project: str, *, background: bool = False) -> str:
        return publish_break(
            folder, project, self.machine, "user:local", self._event, background=background
        )

    def _root(self, project: str) -> Path:
        folder = self._registry.path_of(project)
        if folder is None or not folder.is_dir():
            raise NotFound(f"unknown project {project}")
        return folder

    def _event(
        self, root: Path, project: str, actor: str, kind: str, payload: dict[str, object]
    ) -> None:
        append(
            root,
            machine=self.machine,
            actor=actor,
            type=kind,
            project=project,
            payload=payload,
            contract=CONTRACT,
            now=self._now,
        )
        schedule_index(self.state_dir, project, root)

    def _adopt(self, folder: Path, project: str) -> str:
        place = self._registry.place(project, folder)
        if place != "copy":
            return place
        kept = self._registry.path_of(project)
        if kept is None:
            return place
        seen = str(folder.resolve())
        known = any(
            event.type == "copy_suspected" and event.payload.get("path") == seen
            for event in read_all(kept)
        )
        if not known:
            self._event(
                kept, project, "user:local", "copy_suspected", {"kept": str(kept), "path": seen}
            )
        return place

    def _info(self, folder: Path) -> ProjectInfo:
        data = settings_of(folder)
        raw = data.get("egress", "shielded")
        chosen = raw if raw in {"none", "shielded", "allowed"} else "shielded"
        egress = cast(Egress, chosen)
        return ProjectInfo(id=str(data["id"]), name=folder.name, path=str(folder), egress=egress)

    def projects(self) -> list[ProjectInfo]:
        return [self._info(folder) for _, folder in self._registry.opened if folder.is_dir()]

    def set_egress(self, project: str, egress: str, actor: str) -> ProjectInfo:
        if egress not in {"none", "shielded", "allowed"}:
            raise Invalid(f"unknown egress setting {egress!r}")
        root = self._root(project)
        apply_setting(root, project, egress, actor, self._event)
        return self._info(root)

    def shield_text(self, project: str, text: str, purpose: str = "mcp") -> str:
        return shield_outbound(self._root(project), text, purpose)

    def files(self, project: str) -> list[FileEntry]:
        return file_entries(self._root(project))

    def read(self, project: str, path: str) -> FileContent:
        return read_content(self._root(project), path)

    def save(
        self, project: str, path: str, text: str, actor: str, message: str = ""
    ) -> VersionInfo | None:
        root = self._root(project)
        version = store_edit(root, path, text, actor, message)
        if version is None:
            return None
        self._event(
            root,
            project,
            actor,
            "version",
            {
                "kind": "own_edit",
                "path": relative(path),
                "verdict": "accepted",
                "version": version.id,
            },
        )
        return version

    def history(self, project: str, path: str | None = None) -> list[VersionInfo]:
        return version_history(self._root(project), path)

    def diff(
        self, project: str, path: str, base: str | None = None, target: str | None = None
    ) -> FileDiff:
        return compare_file(self._root(project), path, base, target)

    def restore(self, project: str, path: str, version: str, actor: str) -> VersionInfo:
        root = self._root(project)
        made = restore_file(root, path, version, actor)
        self._event(root, project, actor, "restore", {"path": relative(path), "version": made.id})
        return made

    def _open(self, root: Path, proposal_id: str) -> Proposal:
        found = require(root, Snapshots(root), proposal_id)
        if found.status != "open":
            raise Conflict(f"proposal {proposal_id} is already {found.status}")
        return found

    def propose(
        self,
        project: str,
        changes: Mapping[str, str],
        actor: str,
        reason: str,
        baseline: str | None = None,
    ) -> ProposalInfo:
        root = self._root(project)
        rels = {relative(path): text for path, text in changes.items()}
        for rel in rels:
            if kind_of(rel) not in _TEXT:
                raise Invalid(f"{rel} is not a text file")
            inside(root, rel)
        try:
            made = create(
                root,
                Snapshots(root),
                machine=self.machine,
                project=project,
                changes=rels,
                actor=actor,
                reason=reason,
                baseline=baseline,
                now=self._now,
            )
        except SnapshotError as exc:
            raise NotFound(str(exc)) from exc
        return _info_of(root, made)

    def proposals(self, project: str, status: ProposalStatus | None = "open") -> list[ProposalInfo]:
        root = self._root(project)
        chosen = [
            _info_of(root, item)
            for item in load_all(root, Snapshots(root))
            if status is None or item.status == status
        ]
        return sorted(chosen, key=lambda item: (item.created, item.id), reverse=True)

    def proposal_diff(self, project: str, proposal_id: str) -> list[FileDiff]:
        return diff_files(self._root(project), proposal_id)

    def accept(self, project: str, proposal_id: str, actor: str, reason: str = "") -> VersionInfo:
        root = self._root(project)
        found = self._open(root, proposal_id)
        stale = conflicts(found, Snapshots(root), root)
        if stale:
            self._event(root, project, actor, "conflict", {"paths": stale, "proposal": proposal_id})
            raise Conflict(f"{', '.join(stale)} changed since the proposal was made")
        for rel, data in Snapshots(root).read_draft(found.draft).items():
            write_bytes(inside(root, rel), data)
        note = reason.strip() or reason_text(root, found.reason_ref)
        snaps = Snapshots(root)
        version = snaps.snapshot(tracked_files(root), f"accepted {note}".strip(), actor)
        made = shown(version if version is not None else snaps.head())
        self._event(
            root,
            project,
            actor,
            "verdict",
            {
                "proposal": proposal_id,
                "reason": store_blob(root, note),
                "verdict": "accepted",
                "version": made.id,
            },
        )
        self._compete(root, project, proposal_id, found.paths, actor)
        return made

    def _compete(
        self, root: Path, project: str, proposal_id: str, paths: tuple[str, ...], actor: str
    ) -> None:
        """Mark another open proposal only when this accept changed its baseline."""
        snaps = Snapshots(root)
        for item in load_all(root, snaps):
            if item.id == proposal_id or item.status != "open":
                continue
            if not set(item.paths) & set(paths):
                continue
            stale = conflicts(item, snaps, root)
            if not stale:
                continue
            self._event(root, project, actor, "conflict", {"paths": stale, "proposal": item.id})

    def reject(self, project: str, proposal_id: str, actor: str, reason: str) -> None:
        if not reason.strip():
            raise Invalid("rejecting needs a reason")
        root = self._root(project)
        found = require(root, Snapshots(root), proposal_id)
        if found.status not in {"open", "conflict"}:
            raise Conflict(f"proposal {proposal_id} is already {found.status}")
        self._event(
            root,
            project,
            actor,
            "verdict",
            {"proposal": proposal_id, "reason": store_blob(root, reason), "verdict": "rejected"},
        )

    def log(self, project: str, limit: int = 200) -> list[LogEntry]:
        root = self._root(project)
        return indexed_log(self.state_dir, root, project, limit)

    def log_break(self, project: str) -> str:
        return self._check(self._root(project), project)

    def handover(self, project: str, mode: HandoverMode, target: Path) -> Path:
        return hand_over(self._root(project), mode, target, self.machine, project, self._event)

    def verify(self, project: str) -> VerifyInfo:
        result = verify_all(self._root(project))
        error = None if result.ok else f"line {result.error_line}: {result.reason}"
        return VerifyInfo(ok=result.ok, lines=result.lines, error=error)

    def search(self, project: str, query: str, limit: int = 50) -> list[SearchHit]:
        root = self._root(project)
        return indexed_search(self.state_dir, root, project, query, limit)

    def disk_pull(self, project: str) -> Callable[[], str]:
        self._root(project)
        pending = subscribe(project)
        return lambda: notice(pending.get())
