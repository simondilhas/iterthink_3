"""Real bridge. Versions are snapshots. The log is the decision record."""

from __future__ import annotations

import atexit
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import cast

from iterthink.persistence.snapshots import SnapshotError, Snapshots
from iterthink.services.adhoc_apps import AppsBridge as Apps
from iterthink.services.agent_rules import guarded_propose
from iterthink.services.audit import publish_break
from iterthink.services.bridge import (
    BridgeError,
    Conflict,
    Egress,
    FileContent,
    FileDiff,
    FileEntry,
    FileKind,
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
)
from iterthink.services.change_verdicts import ChangeVerdictsBridge, accept_files, proposal_info
from iterthink.services.chats import ChatsBridge
from iterthink.services.checks_review import ChecksBridge
from iterthink.services.dictation import DictationBridge as Voice
from iterthink.services.disk_scan import notice, scan, start_watching, subscribe
from iterthink.services.documents import DocumentsBridge
from iterthink.services.egress import apply_setting
from iterthink.services.egress import shield_text as shield_outbound
from iterthink.services.erase import EraseBridge
from iterthink.services.event_log import LogCorrupt, append, checkpoint, read_all, store_blob
from iterthink.services.event_log import utc_now as event_now
from iterthink.services.exports import DeliverBridge
from iterthink.services.handover import hand_over
from iterthink.services.impact_review import ImpactBridge as Advice
from iterthink.services.importer_1x import preview as preview_store
from iterthink.services.importer_1x import run_import
from iterthink.services.incoming import IncomingBridge
from iterthink.services.indexer import schedule_index
from iterthink.services.intent import IntentBridge
from iterthink.services.model_views import ModelsBridge
from iterthink.services.plan_render import PlansBridge
from iterthink.services.projects import (
    Registry,
    compare_file,
    default_state_dir,
    file_entries,
    machine_id,
    read_content,
    relative,
    restore_file,
    settings_of,
    store_edit,
    version_history,
)
from iterthink.services.proposals import (
    CONTRACT,
    Later,
    Proposal,
    diff_files,
    load_all,
    require,
)
from iterthink.services.search import indexed_log, indexed_search, with_filters
from iterthink.services.settings import SettingsBridge
from iterthink.services.settings_window import SettingsWindowBridge
from iterthink.services.tasks import TasksBridge, on_verdict
from iterthink.services.verify_log import verify_all
from iterthink.services.watcher import SharedBridge
from iterthink.services.workspaces import WorkspacesBridge as Work


class RealBridge(
    PlansBridge,
    Work,
    Voice,
    IntentBridge,
    SettingsBridge,
    SettingsWindowBridge,
    DocumentsBridge,
    ChatsBridge,
    Advice,
    Apps,
    TasksBridge,
    SharedBridge,
    EraseBridge,
    DeliverBridge,
    IncomingBridge,
    ChecksBridge,
    ModelsBridge,
    ChangeVerdictsBridge,
    Later,
):
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
        return guarded_propose(self, project, changes, actor, reason, baseline)

    def proposals(self, project: str, status: ProposalStatus | None = "open") -> list[ProposalInfo]:
        root = self._root(project)
        chosen = [
            proposal_info(root, item)
            for item in load_all(root, Snapshots(root))
            if status is None or item.status == status
        ]
        return sorted(chosen, key=lambda item: (item.created, item.id), reverse=True)

    def proposal_diff(self, project: str, proposal_id: str) -> list[FileDiff]:
        return diff_files(self._root(project), proposal_id)

    def accept(self, project: str, proposal_id: str, actor: str, reason: str = "") -> VersionInfo:
        found = self._open(self._root(project), proposal_id)
        return accept_files(self, project, found, None, actor, reason)

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
        on_verdict(self, project, proposal_id, "rejected", actor, reason)

    def log(self, project: str, limit: int = 200) -> list[LogEntry]:
        root = self._root(project)
        return indexed_log(self.state_dir, root, project, limit)

    def log_break(self, project: str) -> str:
        return self._check(self._root(project), project)

    def handover(self, project: str, mode: HandoverMode, target: Path) -> Path:
        return hand_over(self._root(project), mode, target, self.machine, project, self._event)

    def import_preview(self, store: Path) -> list[dict[str, object]]:
        return preview_store(store)

    def import_run(self, store: Path, target: Path | None = None) -> list[str]:
        return run_import(store, self, target)

    def verify(self, project: str) -> VerifyInfo:
        result = verify_all(self._root(project))
        error = None if result.ok else f"line {result.error_line}: {result.reason}"
        return VerifyInfo(ok=result.ok, lines=result.lines, error=error)

    def search(
        self,
        project: str,
        query: str,
        limit: int = 50,
        kind: FileKind | None = None,
        in_history: bool = False,
    ) -> list[SearchHit]:
        root = self._root(project)
        text = with_filters(query, kind, in_history)
        return indexed_search(self.state_dir, root, project, text, limit)

    def disk_pull(self, project: str) -> Callable[[], str]:
        self._root(project)
        pending = subscribe(project)
        return lambda: notice(pending.get())
