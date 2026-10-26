"""In-memory bridge for UI and MCP development before the real backend lands.

Source files are real files on disk (the user's folder), so the UI shows
real projects. History, proposals and the decision log live in memory and
vanish on restart. Behaviour must match `tests/v2/contract/`; the real
bridge passes the same tests.

Start the app with ITERTHINK_BRIDGE=fake to use it.
"""

from __future__ import annotations

import csv
import difflib
import hashlib
import io
import json
import secrets
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml

from iterthink.services.bridge import (
    AppInfo,
    Block,
    CellChange,
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
    NotFound,
    ProjectInfo,
    ProposalInfo,
    ProposalStatus,
    SearchHit,
    Segment,
    SettingInfo,
    TaskInfo,
    VerifyInfo,
    VersionInfo,
    kind_of,
)

DATA_DIRS = (".iterthink", ".jj")
TEXT_KINDS = {"markdown", "table", "text"}
MACHINE = "m-fake"
ZERO_HASH = "0" * 64

Snapshot = dict[str, bytes]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _Proposal:
    info: ProposalInfo
    changes: dict[str, str]
    base_content: dict[str, bytes | None]  # None: file did not exist at baseline


@dataclass
class _Project:
    info: ProjectInfo
    root: Path
    versions: list[tuple[VersionInfo, Snapshot]]
    proposals: dict[str, _Proposal]
    log: list[LogEntry]


class FakeBridge:
    """Implements `iterthink.services.bridge.Bridge` for development and tests."""

    def __init__(self, now: Callable[[], datetime] = _utc_now) -> None:
        self._now = now
        self._projects: dict[str, _Project] = {}

    # --- helpers ---------------------------------------------------------

    def _ts(self) -> str:
        return self._now().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _project(self, project: str) -> _Project:
        try:
            return self._projects[project]
        except KeyError:
            raise NotFound(f"unknown project {project}") from None

    @staticmethod
    def _rel(path: str) -> str:
        if not path or "\\" in path or path.startswith("/") or ":" in path.split("/")[0]:
            raise Forbidden(f"path must be relative to the project: {path!r}")
        pure = PurePosixPath(path)
        if any(part in ("..", ".") for part in pure.parts):
            raise Forbidden(f"path leaves the project: {path!r}")
        if pure.parts[0] in DATA_DIRS:
            raise Forbidden(f"iterthink's own data is not a project file: {path!r}")
        if any(part.startswith(".") for part in pure.parts):
            raise Forbidden(f"hidden files are not project files: {path!r}")
        return pure.as_posix()

    def _file(self, p: _Project, path: str) -> Path:
        rel = self._rel(path)
        full = (p.root / rel).resolve()
        if not full.is_relative_to(p.root.resolve()):
            raise Forbidden(f"path leaves the project: {path!r}")
        return full

    @staticmethod
    def _scan(root: Path) -> Snapshot:
        snap: Snapshot = {}
        for full in sorted(root.rglob("*")):
            rel = full.relative_to(root)
            hidden = any(part.startswith(".") for part in rel.parts)
            if hidden or full.suffix == ".claim" or not full.is_file():
                continue
            snap[rel.as_posix()] = full.read_bytes()
        return snap

    def _append_log(self, p: _Project, actor: str, type_: str, summary: str) -> None:
        prev = p.log[-1].hash if p.log else ZERO_HASH
        seq = len(p.log) + 1
        ts = self._ts()
        body = {
            "seq": seq,
            "ts": ts,
            "machine": MACHINE,
            "actor": actor,
            "type": type_,
            "summary": summary,
            "prev_hash": prev,
        }
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        p.log.append(
            LogEntry(
                seq=seq,
                ts=ts,
                machine=MACHINE,
                actor=actor,
                type=type_,
                summary=summary,
                hash=digest,
            )
        )

    def _snapshot(self, p: _Project, actor: str, message: str) -> VersionInfo | None:
        current = self._scan(p.root)
        last = p.versions[-1][1] if p.versions else {}
        changed = tuple(
            sorted(path for path in set(current) | set(last) if current.get(path) != last.get(path))
        )
        if not changed and p.versions:
            return None
        n = len(p.versions) + 1
        vid = f"v{n}-{hashlib.sha256(repr(sorted(current.items())).encode()).hexdigest()[:8]}"
        version = VersionInfo(id=vid, ts=self._ts(), actor=actor, message=message, paths=changed)
        p.versions.append((version, current))
        return version

    def _version(self, p: _Project, vid: str) -> tuple[VersionInfo, Snapshot]:
        for version, snap in p.versions:
            if version.id == vid:
                return version, snap
        raise NotFound(f"unknown version {vid}")

    @staticmethod
    def _read_settings(root: Path) -> dict[str, object]:
        file = root / ".iterthink" / "settings" / "project.yaml"
        if not file.exists():
            return {}
        data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _write_settings(root: Path, data: dict[str, object]) -> None:
        file = root / ".iterthink" / "settings" / "project.yaml"
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")

    def _register(self, root: Path) -> ProjectInfo:
        data = self._read_settings(root)
        pid = str(data["id"])
        if pid in self._projects:
            return self._projects[pid].info
        egress = data.get("egress", "shielded")
        info = ProjectInfo(
            id=pid,
            name=root.name,
            path=str(root.resolve()),
            egress=egress if egress in ("none", "shielded", "allowed") else "shielded",
        )
        p = _Project(info=info, root=root.resolve(), versions=[], proposals={}, log=[])
        self._projects[pid] = p
        self._snapshot(p, "user:local", "opened")
        return info

    # --- projects --------------------------------------------------------

    def open_folder(self, path: Path) -> list[FolderInfo]:
        path = path.expanduser().resolve()
        if not path.is_dir():
            raise NotFound(f"no folder at {path}")
        if self._read_settings(path).get("id"):
            info = self._register(path)
            return [FolderInfo(path=str(path), name=path.name, project_id=info.id)]
        result = []
        for child in sorted(p for p in path.iterdir() if p.is_dir() and not p.name.startswith(".")):
            pid = self._register(child).id if self._read_settings(child).get("id") else None
            result.append(FolderInfo(path=str(child), name=child.name, project_id=pid))
        return result

    def make_project(self, path: Path) -> ProjectInfo:
        path = path.expanduser()
        path = (path if path.is_absolute() else _new_folder(path.as_posix())).resolve()
        if not path.is_dir():
            raise NotFound(f"no folder at {path}")
        if not self._read_settings(path).get("id"):
            self._write_settings(path, {"id": f"p-{secrets.token_hex(4)}", "egress": "shielded"})
            info = self._register(path)
            self._append_log(
                self._projects[info.id],
                "user:local",
                "project_created",
                f"started tracking {path.name}",
            )
            return info
        return self._register(path)

    def projects(self) -> list[ProjectInfo]:
        return [p.info for p in self._projects.values()]

    def set_egress(self, project: str, egress: Egress, actor: str) -> ProjectInfo:
        if egress not in ("none", "shielded", "allowed"):
            raise Invalid(f"unknown egress setting {egress!r}")
        p = self._project(project)
        data = self._read_settings(p.root)
        data["egress"] = egress
        self._write_settings(p.root, data)
        p.info = replace(p.info, egress=egress)
        self._append_log(p, actor, "settings", f"content may leave this machine: {egress}")
        return p.info

    # --- files -----------------------------------------------------------

    def files(self, project: str) -> list[FileEntry]:
        p = self._project(project)
        open_counts: dict[str, int] = {}
        for prop in p.proposals.values():
            if prop.info.status == "open":
                for path in prop.info.paths:
                    open_counts[path] = open_counts.get(path, 0) + 1
        return [
            FileEntry(
                path=path,
                kind=kind_of(path),
                size=len(data),
                open_proposals=open_counts.get(path, 0),
            )
            for path, data in self._scan(p.root).items()
        ]

    def read(self, project: str, path: str) -> FileContent:
        p = self._project(project)
        full = self._file(p, path)
        if not full.is_file():
            raise NotFound(f"no file {path}")
        data = full.read_bytes()
        kind = kind_of(path)
        text = None
        if kind in TEXT_KINDS and full.suffix.lower() != ".xlsx":
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = None
        return FileContent(path=self._rel(path), kind=kind, size=len(data), text=text)

    def save(
        self, project: str, path: str, text: str, actor: str, message: str = ""
    ) -> VersionInfo | None:
        p = self._project(project)
        full = self._file(p, path)
        if kind_of(path) not in TEXT_KINDS or full.suffix.lower() == ".xlsx":
            raise Invalid(f"{path} is not a text file; it can't be edited here")
        new = text.encode("utf-8")
        if full.is_file() and full.read_bytes() == new:
            return None
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(new)
        version = self._snapshot(p, actor, message or f"edited {self._rel(path)}")
        if version is not None:
            self._append_log(p, actor, "verdict", f"saved own edit to {self._rel(path)}")
        return version

    # --- history ---------------------------------------------------------

    def history(self, project: str, path: str | None = None) -> list[VersionInfo]:
        p = self._project(project)
        rel = self._rel(path) if path else None
        return [v for v, _ in reversed(p.versions) if rel is None or rel in v.paths]

    def diff(
        self, project: str, path: str, base: str | None = None, target: str | None = None
    ) -> FileDiff:
        p = self._project(project)
        rel = self._rel(path)
        if target is None:
            full = self._file(p, rel)
            after = full.read_bytes() if full.is_file() else None
        else:
            after = self._version(p, target)[1].get(rel)
        if base is None:
            before = None
            for _, snap in reversed(p.versions):
                if snap.get(rel) != after:
                    before = snap.get(rel)
                    break
            else:
                return FileDiff(path=rel, kind="none", summary="no earlier version differs")
        else:
            before = self._version(p, base)[1].get(rel)
        return diff_bytes(rel, before, after)

    def model_glb(self, project: str, key: str, part: Literal["before", "after", "diff"]) -> bytes:
        self._project(project)
        raise NotFound(f"the fake renders no model views ({part} of {key[:12]})")

    def diff_progress(
        self, project: str, path: str, base: str | None = None, target: str | None = None
    ) -> Mapping[str, int]:
        self._project(project)
        return {}

    def restore(self, project: str, path: str, version: str, actor: str) -> VersionInfo:
        p = self._project(project)
        rel = self._rel(path)
        version_info, snap = self._version(p, version)
        if rel not in snap:
            raise NotFound(f"{rel} did not exist in that version")
        self._file(p, rel).write_bytes(snap[rel])
        new = self._snapshot(p, actor, f"restored {rel} from {version_info.ts}")
        if new is None:
            return p.versions[-1][0]
        self._append_log(p, actor, "restore", f"restored {rel} from {version_info.ts}")
        return new

    # --- proposals -------------------------------------------------------

    def propose(
        self,
        project: str,
        changes: Mapping[str, str],
        actor: str,
        reason: str,
        baseline: str | None = None,
    ) -> ProposalInfo:
        p = self._project(project)
        if not reason.strip():
            raise Invalid("a proposal needs a reason")
        if not changes:
            raise Invalid("a proposal needs at least one change")
        rels = {self._rel(path): text for path, text in changes.items()}
        for rel in rels:
            if kind_of(rel) not in TEXT_KINDS:
                raise Invalid(f"{rel} is not a text file")
            self._file(p, rel)
        base_version, base_snap = self._version(p, baseline) if baseline else p.versions[-1]
        current = self._scan(p.root)
        base_content = {
            rel: current.get(rel) if baseline is None else base_snap.get(rel) for rel in rels
        }
        info = ProposalInfo(
            id=f"pr-{secrets.token_hex(4)}",
            baseline=base_version.id,
            actor=actor,
            reason=reason,
            paths=tuple(sorted(rels)),
            status="open",
            created=self._ts(),
        )
        p.proposals[info.id] = _Proposal(info=info, changes=rels, base_content=base_content)
        self._append_log(
            p, actor, "proposal_created", f"proposed changes to {', '.join(info.paths)}: {reason}"
        )
        return info

    def proposals(self, project: str, status: ProposalStatus | None = "open") -> list[ProposalInfo]:
        p = self._project(project)
        items = [
            prop.info
            for prop in p.proposals.values()
            if status is None or prop.info.status == status
        ]
        return sorted(items, key=lambda i: (i.created, i.id), reverse=True)

    def _proposal(self, p: _Project, proposal_id: str) -> _Proposal:
        try:
            return p.proposals[proposal_id]
        except KeyError:
            raise NotFound(f"unknown proposal {proposal_id}") from None

    def proposal_diff(self, project: str, proposal_id: str) -> list[FileDiff]:
        p = self._project(project)
        prop = self._proposal(p, proposal_id)
        return [
            diff_bytes(rel, prop.base_content[rel], text.encode("utf-8"))
            for rel, text in sorted(prop.changes.items())
        ]

    def _decide(self, p: _Project, prop: _Proposal, status: ProposalStatus, actor: str) -> None:
        prop.info = replace(prop.info, status=status, decided_by=actor)

    def accept(self, project: str, proposal_id: str, actor: str, reason: str = "") -> VersionInfo:
        p = self._project(project)
        prop = self._proposal(p, proposal_id)
        if prop.info.status != "open":
            raise Conflict(f"proposal {proposal_id} is already {prop.info.status}")
        current = self._scan(p.root)
        stale = [rel for rel in prop.changes if current.get(rel) != prop.base_content[rel]]
        if stale:
            self._decide(p, prop, "conflict", actor)
            self._append_log(
                p,
                actor,
                "conflict",
                f"proposal {proposal_id} conflicts with later changes to {', '.join(stale)}",
            )
            raise Conflict(f"{', '.join(stale)} changed since the proposal was made")
        for rel, text in prop.changes.items():
            full = self._file(p, rel)
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_bytes(text.encode("utf-8"))
        note = f": {reason}" if reason else ""
        version = self._snapshot(p, actor, f"accepted {proposal_id}{note}")
        self._decide(p, prop, "accepted", actor)
        self._append_log(
            p, actor, "verdict", f"accepted proposal {proposal_id}: {prop.info.reason}{note}"
        )
        return version if version is not None else p.versions[-1][0]

    def reject(self, project: str, proposal_id: str, actor: str, reason: str) -> None:
        p = self._project(project)
        prop = self._proposal(p, proposal_id)
        if not reason.strip():
            raise Invalid("rejecting needs a reason")
        if prop.info.status != "open":
            raise Conflict(f"proposal {proposal_id} is already {prop.info.status}")
        self._decide(p, prop, "rejected", actor)
        self._append_log(p, actor, "verdict", f"rejected proposal {proposal_id}: {reason}")

    # --- log, search -----------------------------------------------------

    def log(self, project: str, limit: int = 200) -> list[LogEntry]:
        return list(reversed(self._project(project).log))[:limit]

    def verify(self, project: str) -> VerifyInfo:
        prev = ZERO_HASH
        entries = self._project(project).log
        for entry in entries:
            body = {
                "seq": entry.seq,
                "ts": entry.ts,
                "machine": entry.machine,
                "actor": entry.actor,
                "type": entry.type,
                "summary": entry.summary,
                "prev_hash": prev,
            }
            digest = hashlib.sha256(
                json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            ).hexdigest()
            if digest != entry.hash:
                return VerifyInfo(
                    ok=False,
                    lines=entry.seq - 1,
                    error=f"machine {entry.machine}, line {entry.seq}: hash mismatch",
                )
            prev = digest
        return VerifyInfo(ok=True, lines=len(entries), error=None)

    def search(
        self,
        project: str,
        query: str,
        limit: int = 50,
        kind: FileKind | None = None,
        in_history: bool = False,
    ) -> list[SearchHit]:
        needle = query.strip().casefold()
        if not needle:
            return []
        p = self._project(project)
        snaps = [self._scan(p.root)]
        if in_history:
            snaps += [snap for _, snap in reversed(p.versions)]
        hits: list[SearchHit] = []
        for snap in snaps:
            for rel, data in snap.items():
                if kind is None or kind_of(rel) == kind:
                    hits.extend(_hits_in(rel, data, needle))
        return list(dict.fromkeys(hits))[:limit]

    # --- later slices ----------------------------------------------------

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
        raise NotImplementedError("slice A7")

    def edit_change(
        self,
        project: str,
        proposal_id: str,
        change_id: str,
        text: str,
        actor: str,
        candidate: str | None = None,
    ) -> ProposalInfo:
        raise NotImplementedError("slice A7")

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

    def task_claim(self, project: str, task_id: str, actor: str, client: str) -> TaskInfo:
        raise NotImplementedError("slice C8")

    def task_update(self, project: str, task_id: str, progress: str, actor: str) -> TaskInfo:
        raise NotImplementedError("slice C8")

    def task_ask(self, project: str, task_id: str, question: str, actor: str) -> TaskInfo:
        raise NotImplementedError("slice C8")

    def task_answer(self, project: str, task_id: str, text: str, actor: str) -> TaskInfo:
        raise NotImplementedError("slice C8")

    def task_complete(self, project: str, task_id: str, summary: str, actor: str) -> TaskInfo:
        raise NotImplementedError("slice C8")

    def task_cancel(self, project: str, task_id: str, actor: str) -> TaskInfo:
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


def _hits_in(rel: str, data: bytes, needle: str) -> list[SearchHit]:
    hits: list[SearchHit] = []
    if needle in rel.casefold():
        hits.append(SearchHit(path=rel, line=0, snippet=rel))
    if kind_of(rel) not in TEXT_KINDS:
        return hits
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return hits
    for n, line in enumerate(lines, 1):
        if needle in line.casefold():
            hits.append(SearchHit(path=rel, line=n, snippet=line.strip()[:200]))
    return hits


def _new_folder(name: str) -> Path:
    """A new folder in the default workspace; an existing name gets a number."""
    from iterthink import config

    root = config.DOCUMENTS.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    stem = PurePosixPath(name).name.strip() or "Project"
    chosen = root / stem
    number = 2
    while chosen.exists():
        chosen = root / f"{stem} {number}"
        number += 1
    chosen.mkdir()
    return chosen


# --- diffs (simple engines; the real ones come from compare/, slice A4) ------


def _paragraphs(text: str) -> list[str]:
    return [block.strip() for block in text.replace("\r\n", "\n").split("\n\n") if block.strip()]


def _segments(before: str, after: str) -> tuple[Segment, ...]:
    a, b = before.split(" "), after.split(" ")
    out: list[Segment] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(Segment("equal", " ".join(a[i1:i2])))
        if op in ("delete", "replace"):
            out.append(Segment("delete", " ".join(a[i1:i2])))
        if op in ("insert", "replace"):
            out.append(Segment("insert", " ".join(b[j1:j2])))
    return tuple(out)


def _text_diff(path: str, before: str, after: str) -> FileDiff:
    a, b = _paragraphs(before), _paragraphs(after)
    blocks: list[Block] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            blocks += [Block("stable", x, x) for x in a[i1:i2]]
        elif op == "delete":
            blocks += [Block("removed", x, "") for x in a[i1:i2]]
        elif op == "insert":
            blocks += [Block("added", "", y) for y in b[j1:j2]]
        else:
            olds, news = a[i1:i2], b[j1:j2]
            for k in range(max(len(olds), len(news))):
                old = olds[k] if k < len(olds) else ""
                new = news[k] if k < len(news) else ""
                if old and new:
                    blocks.append(Block("modified", old, new, _segments(old, new)))
                elif old:
                    blocks.append(Block("removed", old, ""))
                else:
                    blocks.append(Block("added", "", new))
    counts = {k: sum(1 for x in blocks if x.kind == k) for k in ("modified", "added", "removed")}
    parts = [f"{n} paragraph{'s' if n != 1 else ''} {k}" for k, n in counts.items() if n]
    return FileDiff(
        path=path, kind="text", summary=", ".join(parts) or "no changes", blocks=tuple(blocks)
    )


def _rows(text: str, path: str) -> list[list[str]]:
    delimiter = "\t" if path.lower().endswith(".tsv") else ","
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter) if row]


def _table_diff(path: str, before: str, after: str) -> FileDiff:
    a, b = _rows(before, path), _rows(after, path)
    columns = tuple(b[0] if b else a[0] if a else [])
    old = {row[0]: row for row in a[1:]}
    new = {row[0]: row for row in b[1:]}
    added = tuple(tuple(new[k]) for k in new if k not in old)
    removed = tuple(tuple(old[k]) for k in old if k not in new)
    changes: list[CellChange] = []
    for key in (k for k in new if k in old):
        for i, col in enumerate(columns):
            x = old[key][i] if i < len(old[key]) else ""
            y = new[key][i] if i < len(new[key]) else ""
            if x != y:
                changes.append(CellChange(row=key, column=col, before=x, after=y))
    parts = []
    if changes:
        parts.append(f"{len(changes)} cell{'s' if len(changes) != 1 else ''} changed")
    if added:
        parts.append(f"{len(added)} row{'s' if len(added) != 1 else ''} added")
    if removed:
        parts.append(f"{len(removed)} row{'s' if len(removed) != 1 else ''} removed")
    return FileDiff(
        path=path,
        kind="table",
        summary=", ".join(parts) or "no changes",
        added_rows=added,
        removed_rows=removed,
        cell_changes=tuple(changes),
        columns=columns,
    )


def diff_bytes(path: str, before: bytes | None, after: bytes | None) -> FileDiff:
    """Diff two states of one file; None means the file does not exist."""
    if before == after:
        return FileDiff(path=path, kind="none", summary="no changes")
    kind = kind_of(path)
    try:
        a = (before or b"").decode("utf-8")
        b = (after or b"").decode("utf-8")
    except UnicodeDecodeError:
        return FileDiff(path=path, kind="binary", summary="file changed")
    if kind == "table" and not path.lower().endswith(".xlsx"):
        return _table_diff(path, a, b)
    if kind in ("markdown", "text"):
        return _text_diff(path, a, b)
    return FileDiff(path=path, kind="binary", summary="file changed")
