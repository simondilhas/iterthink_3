"""Runtime calls an app may make. Writes go through propose."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, cast

from iterthink.persistence.snapshots import Snapshots
from iterthink.services.app_validate import ALLOWED
from iterthink.services.bridge import (
    BridgeError,
    FileContent,
    FileDiff,
    FileEntry,
    ProposalInfo,
    SearchHit,
    VersionInfo,
)
from iterthink.services.event_log import utc_now
from iterthink.services.projects import tracked_files
from iterthink.services.proposals import create as create_proposal

_WRITES = "only propose can write"


class _Host(Protocol):
    def files(self, project: str) -> list[FileEntry]: ...
    def read(self, project: str, path: str) -> FileContent: ...
    def history(self, project: str, path: str | None = None) -> list[VersionInfo]: ...
    def search(self, project: str, query: str, limit: int = 50) -> list[SearchHit]: ...
    def diff(
        self, project: str, path: str, base: str | None = None, target: str | None = None
    ) -> FileDiff: ...
    def propose(
        self,
        project: str,
        changes: Mapping[str, str],
        actor: str,
        reason: str,
        baseline: str | None = None,
    ) -> ProposalInfo: ...


def perform(host: _Host, project: str, name: str, args: object, actor: str, *, dry: bool) -> object:
    """Run one allowlisted call. `dry` records propose and does not apply it."""
    if name not in ALLOWED:
        return {"error": _WRITES}
    if name == "listFiles":
        return _list(host, project)
    if name == "readFile":
        return _read(host, project, args)
    if name == "history":
        return _history(host, project, args)
    if name == "search":
        return _search(host, project, args)
    if name == "compare":
        return _compare(host, project, args)
    if name == "propose":
        return _propose(host, project, args, actor, dry)
    return {"error": _WRITES}


def _args(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return cast(dict[str, object], value)


def _text(args: Mapping[str, object], key: str) -> str:
    found = args.get(key)
    return found if isinstance(found, str) else ""


def _list(host: _Host, project: str) -> list[dict[str, object]]:
    rows = host.files(project)
    return [{"path": item.path, "kind": item.kind, "size": item.size} for item in rows]


def _read(host: _Host, project: str, args: object) -> dict[str, object]:
    path = _text(_args(args), "path")
    if not path:
        return {"error": "readFile needs a path"}
    try:
        content = host.read(project, path)
    except BridgeError as exc:
        return {"error": str(exc)}
    return {
        "path": content.path,
        "kind": content.kind,
        "size": content.size,
        "text": content.text,
    }


def _history(host: _Host, project: str, args: object) -> list[dict[str, object]]:
    path = _text(_args(args), "path") or None
    rows = host.history(project, path)
    return [
        {"id": item.id, "ts": item.ts, "actor": item.actor, "message": item.message}
        for item in rows
    ]


def _search(host: _Host, project: str, args: object) -> list[dict[str, object]]:
    query = _text(_args(args), "query")
    raw = _args(args).get("limit", 20)
    limit = raw if isinstance(raw, int) and not isinstance(raw, bool) else 20
    rows = host.search(project, query, limit)
    return [{"path": item.path, "line": item.line, "snippet": item.snippet} for item in rows]


def _compare(host: _Host, project: str, args: object) -> dict[str, object]:
    body = _args(args)
    path = _text(body, "path")
    if not path:
        return {"error": "compare needs a path"}
    base = _text(body, "base") or None
    target = _text(body, "target") or None
    try:
        diff = host.diff(project, path, base, target)
    except BridgeError as exc:
        return {"error": str(exc)}
    return {"path": diff.path, "kind": diff.kind, "summary": diff.summary}


def stage_revision(
    root: Path, machine: str, project: str, slug: str, html: str, actor: str, reason: str
) -> str:
    """Store new app code as a proposal. The current file stays until it is accepted."""
    rel = f".iterthink/apps/{slug}/index.html"
    snaps = Snapshots(root)
    files = tracked_files(root)
    files[rel] = (root / rel).read_bytes()
    version = snaps.snapshot(files, "app", actor)
    baseline = version.id if version is not None else snaps.head().id
    made = create_proposal(
        root,
        snaps,
        machine=machine,
        project=project,
        changes={rel: html},
        actor=actor,
        reason=reason.strip() or "change the app",
        baseline=baseline,
        now=utc_now,
    )
    return made.id


def _propose(host: _Host, project: str, args: object, actor: str, dry: bool) -> dict[str, object]:
    body = _args(args)
    changes = body.get("changes")
    reason = _text(body, "reason")
    if not isinstance(changes, dict) or not reason.strip():
        return {"error": "propose needs changes and a reason"}
    text = {str(key): value for key, value in changes.items() if isinstance(value, str)}
    if dry:
        return {"recorded": True, "paths": list(text)}
    try:
        info = host.propose(project, text, actor, reason)
    except BridgeError as exc:
        return {"error": str(exc)}
    return {"id": info.id, "status": info.status, "paths": list(info.paths)}
