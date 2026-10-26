"""The bridge: the one interface every surface (web UI, MCP, ad-hoc apps, CLI) calls.

This file is the contract. It is written by a human, not by slices: agents
implement it, they do not change it. A slice that needs a new method or field
records the proposal in its run report.

Two implementations:
- `bridge_fake.FakeBridge`: real source files on disk, history and log in
  memory. Lets UI and MCP work start before the backend exists.
- `bridge_real.RealBridge` (slice B1): content-addressed snapshots, event log, diff engines, index.

Both must pass `tests/v2/contract/`. Methods marked `# slice Xn` raise
`NotImplementedError` until that slice lands, in both implementations.

Conventions
- `project` is the project id from `.iterthink/settings/project.yaml`.
- `path` is POSIX, relative to the project root. Paths that escape the
  project or point into `.iterthink/` or `.jj/` raise `Forbidden`.
- `actor` is `user:<name>`, `agent:<name>`, `app:<id>` or `rule:<id>`.
- Version ids are opaque strings. Timestamps are UTC `YYYY-MM-DDTHH:MM:SSZ`.
- Nothing returned here leaks Git or jj vocabulary.

The vocabulary, errors and records live in `bridge_records.py` and are
re-exported here: surfaces import everything from this module.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Literal, Protocol, cast

from iterthink.services.bridge_records import (
    KIND_BY_SUFFIX,
    AppInfo,
    Block,
    BridgeError,
    CellChange,
    ChangeStatus,
    ChatInfo,
    ChatMessage,
    Conflict,
    Egress,
    ExportInfo,
    FileContent,
    FileDiff,
    FileEntry,
    FileKind,
    FolderInfo,
    Forbidden,
    HandoverMode,
    Intent,
    Invalid,
    LogEntry,
    Mode,
    NotFound,
    ProjectInfo,
    ProposalInfo,
    ProposalStatus,
    SearchHit,
    Segment,
    SettingInfo,
    TaskInfo,
    TaskStatus,
    VerifyInfo,
    VersionInfo,
    kind_of,
)

__all__ = [
    "KIND_BY_SUFFIX",
    "AppInfo",
    "Block",
    "Bridge",
    "BridgeError",
    "CellChange",
    "ChangeStatus",
    "ChatInfo",
    "ChatMessage",
    "Conflict",
    "Egress",
    "ExportInfo",
    "FileContent",
    "FileDiff",
    "FileEntry",
    "FileKind",
    "FolderInfo",
    "Forbidden",
    "HandoverMode",
    "Intent",
    "Invalid",
    "LogEntry",
    "Mode",
    "NotFound",
    "ProjectInfo",
    "ProposalInfo",
    "ProposalStatus",
    "SearchHit",
    "Segment",
    "SettingInfo",
    "TaskInfo",
    "TaskStatus",
    "VerifyInfo",
    "VersionInfo",
    "get_bridge",
    "kind_of",
]


# --- the contract ------------------------------------------------------------


class Bridge(Protocol):
    # projects (slice B1 real; fake now)
    def open_folder(self, path: Path) -> list[FolderInfo]:
        """The folder itself if it is a project, else its first-level subfolders."""
        ...

    def make_project(self, path: Path) -> ProjectInfo:
        """Start tracking a folder. Never moves or changes its source files.
        A relative path names a new folder in the default workspace; it is created,
        and an existing folder of that name gets a number appended."""
        ...

    def projects(self) -> list[ProjectInfo]:
        """Projects opened on this machine."""
        ...

    def set_egress(self, project: str, egress: Egress, actor: str) -> ProjectInfo: ...

    # files
    def files(self, project: str) -> list[FileEntry]: ...
    def read(self, project: str, path: str) -> FileContent: ...
    def save(
        self, project: str, path: str, text: str, actor: str, message: str = ""
    ) -> VersionInfo | None:
        """A user's own edit: writes the file, creates a version, logs it as the
        user's verdict. Returns None if the content did not change."""
        ...

    # history
    def history(self, project: str, path: str | None = None) -> list[VersionInfo]:
        """Newest first."""
        ...

    def diff(
        self, project: str, path: str, base: str | None = None, target: str | None = None
    ) -> FileDiff:
        """target None = current file; base None = the version before target."""
        ...

    def restore(self, project: str, path: str, version: str, actor: str) -> VersionInfo:
        """New version with the file as it was in `version`. History only grows."""
        ...

    # proposals and verdicts
    def propose(
        self,
        project: str,
        changes: Mapping[str, str],
        actor: str,
        reason: str,
        baseline: str | None = None,
    ) -> ProposalInfo:
        """Changes to text files. Source files stay untouched until accepted."""
        ...

    def proposals(
        self, project: str, status: ProposalStatus | None = "open"
    ) -> list[ProposalInfo]: ...
    def proposal_diff(self, project: str, proposal_id: str) -> list[FileDiff]: ...
    def accept(
        self, project: str, proposal_id: str, actor: str, reason: str = ""
    ) -> VersionInfo: ...
    def reject(self, project: str, proposal_id: str, actor: str, reason: str) -> None: ...

    # per-change verdicts — slice A7
    def decide_change(
        self,
        project: str,
        proposal_id: str,
        change_id: str,
        verdict: Literal["accepted", "rejected"],
        actor: str,
        reason: str = "",
        candidate: str | None = None,
    ) -> ProposalInfo:
        """One change of an open proposal. `candidate` is the hash the screen showed:
        a different current hash raises Conflict and nothing is decided. Once every
        change is decided, the accepted ones become one version and the proposal is
        accepted, or rejected when none was accepted."""
        ...

    def edit_change(
        self,
        project: str,
        proposal_id: str,
        change_id: str,
        text: str,
        actor: str,
        candidate: str | None = None,
    ) -> ProposalInfo:
        """Replace the proposed text of one change. The change stays open."""
        ...

    # decision log
    def log(self, project: str, limit: int = 200) -> list[LogEntry]:
        """Newest first, all machines merged."""
        ...

    def verify(self, project: str) -> VerifyInfo: ...

    # search (keyword, no AI; live while typing)
    def search(
        self,
        project: str,
        query: str,
        limit: int = 50,
        kind: FileKind | None = None,
        in_history: bool = False,
    ) -> list[SearchHit]:
        """`kind` keeps hits in files of that kind; `in_history` also searches
        earlier versions."""
        ...

    # the line — slice C3
    def interpret(self, project: str, line: str) -> Intent: ...

    # chats — slice C5
    def chat_start(self, project: str, text: str, actor: str) -> ChatInfo: ...
    def chat_send(self, project: str, chat_id: str, text: str, actor: str) -> Iterator[str]:
        """Streams the answer in chunks; the full exchange lands in the chat file."""
        ...

    def chat_messages(self, project: str, chat_id: str) -> list[ChatMessage]: ...
    def chats(self, project: str) -> list[ChatInfo]: ...

    # ad-hoc apps — slice C6
    def app_build(self, project: str, request: str, actor: str) -> AppInfo: ...
    def app_run(self, project: str, app_id: str) -> AppInfo: ...
    def app_keep(self, project: str, app_id: str, actor: str) -> AppInfo: ...
    def app_discard(self, project: str, app_id: str, actor: str) -> AppInfo: ...
    def apps(self, project: str) -> list[AppInfo]: ...

    # tasks and agents — slice C8
    def task_create(
        self, project: str, title: str, body: str, actor: str, depends_on: tuple[str, ...] = ()
    ) -> TaskInfo: ...
    def task_start(self, project: str, task_id: str, actor: str) -> TaskInfo: ...
    def tasks(self, project: str) -> list[TaskInfo]: ...
    def task_claim(self, project: str, task_id: str, actor: str, client: str) -> TaskInfo:
        """An agent takes a ready task; it moves to running. A held claim raises Conflict."""
        ...

    def task_update(self, project: str, task_id: str, progress: str, actor: str) -> TaskInfo: ...
    def task_ask(self, project: str, task_id: str, question: str, actor: str) -> TaskInfo:
        """The agent needs a human; the task moves to needs-input."""
        ...

    def task_answer(self, project: str, task_id: str, text: str, actor: str) -> TaskInfo: ...
    def task_complete(self, project: str, task_id: str, summary: str, actor: str) -> TaskInfo:
        """The agent is done; the task moves to review. A human decides from there."""
        ...

    def task_cancel(self, project: str, task_id: str, actor: str) -> TaskInfo: ...

    # deliver closed — slice C12
    def export(
        self, project: str, path: str, format: str, template: str | None = None
    ) -> ExportInfo: ...
    def import_returned(
        self, project: str, returned: Path, source: str, actor: str
    ) -> ProposalInfo:
        """An edited DOCX/XLSX back from a client becomes a proposal to the source."""
        ...

    # handover — slice C13
    def handover(self, project: str, mode: HandoverMode, target: Path) -> Path: ...

    # settings — slice C15
    def settings(self, project: str) -> list[SettingInfo]: ...


# --- selection ---------------------------------------------------------------


def get_bridge(root: Path | None = None) -> Bridge:
    """ITERTHINK_BRIDGE=fake|real (default: real once it exists, else fake)."""
    choice = os.environ.get("ITERTHINK_BRIDGE", "").lower()
    if choice != "fake":
        try:
            from iterthink.services.bridge_real import RealBridge
        except ImportError:
            if choice == "real":
                raise
        else:
            return cast(Bridge, RealBridge(state_dir=root))
    from iterthink.services.bridge_fake import FakeBridge

    return FakeBridge()
