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
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, cast

# --- vocabulary --------------------------------------------------------------

Egress = Literal["none", "shielded", "allowed"]
FileKind = Literal["markdown", "table", "plan", "model", "image", "document", "text", "other"]
ProposalStatus = Literal["open", "accepted", "rejected", "conflict"]
Mode = Literal["search", "document", "chat", "app", "task"]
TaskStatus = Literal["todo", "running", "review", "done", "failed"]
HandoverMode = Literal["full", "client"]

KIND_BY_SUFFIX: dict[str, FileKind] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".csv": "table",
    ".tsv": "table",
    ".xlsx": "table",
    ".pdf": "plan",
    ".ifc": "model",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".docx": "document",
    ".txt": "text",
    ".json": "text",
    ".yaml": "text",
    ".yml": "text",
    ".html": "text",
}


def kind_of(path: str) -> FileKind:
    """File kind from the suffix, case-insensitive."""
    return KIND_BY_SUFFIX.get(Path(path).suffix.lower(), "other")


# --- errors ------------------------------------------------------------------


class BridgeError(Exception):
    """Base class. Surfaces show `str(error)` to the user."""


class NotFound(BridgeError):
    """Unknown project, path, version, proposal, chat, app or task."""


class Forbidden(BridgeError):
    """Path outside the project, egress blocks the call, or the actor may not do this."""


class Conflict(BridgeError):
    """Already decided, stale baseline that cannot be applied, or a held claim."""


class Invalid(BridgeError):
    """Malformed input: empty reason on reject, binary save, unknown mode."""


# --- records -----------------------------------------------------------------


@dataclass(frozen=True)
class FolderInfo:
    path: str  # absolute
    name: str
    project_id: str | None  # None: not a project yet


@dataclass(frozen=True)
class ProjectInfo:
    id: str
    name: str
    path: str  # absolute, as seen on this machine
    egress: Egress


@dataclass(frozen=True)
class FileEntry:
    path: str
    kind: FileKind
    size: int
    open_proposals: int


@dataclass(frozen=True)
class FileContent:
    path: str
    kind: FileKind
    size: int
    text: str | None  # None for binary files


@dataclass(frozen=True)
class VersionInfo:
    id: str
    ts: str
    actor: str
    message: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class Segment:
    op: Literal["equal", "insert", "delete"]
    text: str


@dataclass(frozen=True)
class Block:
    """One paragraph-level unit of a text diff."""

    kind: Literal["stable", "refined", "modified", "rephrased", "added", "removed"]
    before: str
    after: str
    segments: tuple[Segment, ...] = ()


@dataclass(frozen=True)
class CellChange:
    row: str  # row key (first column) or row number as string
    column: str
    before: str
    after: str


@dataclass(frozen=True)
class FileDiff:
    path: str
    kind: Literal["text", "table", "plan", "model", "binary", "none"]
    summary: str  # one line, plain words: "2 paragraphs changed, 1 added"
    blocks: tuple[Block, ...] = ()
    added_rows: tuple[tuple[str, ...], ...] = ()
    removed_rows: tuple[tuple[str, ...], ...] = ()
    cell_changes: tuple[CellChange, ...] = ()
    columns: tuple[str, ...] = ()
    details: Mapping[str, object] = field(default_factory=dict)  # engine-specific (plan, model)


@dataclass(frozen=True)
class ProposalInfo:
    id: str
    baseline: str  # version id
    actor: str
    reason: str
    paths: tuple[str, ...]
    status: ProposalStatus
    created: str
    decided_by: str | None = None  # actor, or "rule:<id>" for automatic verdicts


@dataclass(frozen=True)
class LogEntry:
    seq: int
    ts: str
    machine: str
    actor: str
    type: str
    summary: str  # plain words, e.g. "accepted proposal pr-1a2b: fix door type"
    hash: str


@dataclass(frozen=True)
class VerifyInfo:
    ok: bool
    lines: int
    error: str | None  # "machine m-7f3a, line 42: hash mismatch"


@dataclass(frozen=True)
class SearchHit:
    path: str
    line: int
    snippet: str


@dataclass(frozen=True)
class Intent:
    mode: Mode
    title: str
    plan: tuple[str, ...]  # short steps shown before anything runs


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["user", "assistant", "system"]
    text: str
    ts: str


@dataclass(frozen=True)
class ChatInfo:
    id: str
    title: str
    path: str  # .iterthink/chats/<id>.md
    references: tuple[str, ...]  # project paths


@dataclass(frozen=True)
class AppInfo:
    id: str
    title: str
    status: Literal["draft", "kept", "discarded"]
    url: str | None  # on the app origin, while running


@dataclass(frozen=True)
class TaskInfo:
    id: str
    title: str
    path: str  # .iterthink/tasks/<id>.md
    status: TaskStatus
    depends_on: tuple[str, ...]
    runner: str | None  # machine running it
    proposals: tuple[str, ...]


@dataclass(frozen=True)
class ExportInfo:
    path: str  # .iterthink/exports/...
    source_version: str
    format: Literal["docx", "xlsx", "pdf", "csv"]


@dataclass(frozen=True)
class SettingInfo:
    key: str
    value: object
    source: Literal["default", "workspace", "project"]


# --- the contract ------------------------------------------------------------


class Bridge(Protocol):
    # projects (slice B1 real; fake now)
    def open_folder(self, path: Path) -> list[FolderInfo]:
        """The folder itself if it is a project, else its first-level subfolders."""
        ...

    def make_project(self, path: Path) -> ProjectInfo:
        """Start tracking a folder. Never moves or changes its source files."""
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

    # decision log
    def log(self, project: str, limit: int = 200) -> list[LogEntry]:
        """Newest first, all machines merged."""
        ...

    def verify(self, project: str) -> VerifyInfo: ...

    # search (keyword, no AI; live while typing)
    def search(self, project: str, query: str, limit: int = 50) -> list[SearchHit]: ...

    # the line — slice C2
    def interpret(self, project: str, line: str) -> Intent: ...

    # chats — slice C3
    def chat_start(self, project: str, text: str, actor: str) -> ChatInfo: ...
    def chat_send(self, project: str, chat_id: str, text: str, actor: str) -> Iterator[str]:
        """Streams the answer in chunks; the full exchange lands in the chat file."""
        ...

    def chat_messages(self, project: str, chat_id: str) -> list[ChatMessage]: ...
    def chats(self, project: str) -> list[ChatInfo]: ...

    # ad-hoc apps — slice C5
    def app_build(self, project: str, request: str, actor: str) -> AppInfo: ...
    def app_run(self, project: str, app_id: str) -> AppInfo: ...
    def app_keep(self, project: str, app_id: str, actor: str) -> AppInfo: ...
    def app_discard(self, project: str, app_id: str, actor: str) -> AppInfo: ...
    def apps(self, project: str) -> list[AppInfo]: ...

    # tasks and agents — slice C6
    def task_create(
        self, project: str, title: str, body: str, actor: str, depends_on: tuple[str, ...] = ()
    ) -> TaskInfo: ...
    def task_start(self, project: str, task_id: str, actor: str) -> TaskInfo: ...
    def tasks(self, project: str) -> list[TaskInfo]: ...

    # deliver closed — slice C10
    def export(
        self, project: str, path: str, format: str, template: str | None = None
    ) -> ExportInfo: ...
    def import_returned(
        self, project: str, returned: Path, source: str, actor: str
    ) -> ProposalInfo:
        """An edited DOCX/XLSX back from a client becomes a proposal to the source."""
        ...

    # handover — slice C11
    def handover(self, project: str, mode: HandoverMode, target: Path) -> Path: ...

    # settings — slice C13
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
