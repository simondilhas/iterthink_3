"""Vocabulary, errors and records of the bridge contract. Re-exported by `bridge.py`;
import them from there."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# --- vocabulary --------------------------------------------------------------

Egress = Literal["none", "shielded", "allowed"]
FileKind = Literal["markdown", "table", "plan", "model", "image", "document", "text", "other"]
ProposalStatus = Literal["open", "accepted", "rejected", "conflict"]
Mode = Literal["search", "document", "chat", "app", "task", "review"]
TaskStatus = Literal[
    "backlog", "ready", "running", "needs-input", "review", "done", "rejected", "cancelled"
]
ChangeStatus = Literal["open", "accepted", "rejected"]
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
    id: str = ""  # change id for a per-change verdict; "" when not decidable alone


@dataclass(frozen=True)
class CellChange:
    row: str  # row key (first column) or row number as string
    column: str
    before: str
    after: str
    id: str = ""  # change id for a per-change verdict; "" when not decidable alone


@dataclass(frozen=True)
class FileDiff:
    path: str
    kind: Literal["text", "table", "plan", "model", "image", "binary", "none"]
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
    changes: Mapping[str, ChangeStatus] = field(default_factory=dict)  # change id → status
    candidate: str = ""  # sha256 over the proposed files; changes when a change is edited


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
    url: str | None  # None: the shell delivers the app by `srcdoc`, there is no app origin


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
