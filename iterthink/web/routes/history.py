"""History panel, a version, its diff, and restore."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from iterthink.services.bridge import Bridge, FileDiff, VersionInfo
from iterthink.web.app import actor_of, bridge_of
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)
_actor = Depends(actor_of)
_path = Form()
_version_field = Form()


def who(actor: str) -> str:
    """`user:simon` is simon. `agent:checker` is agent checker."""
    kind, _, name = actor.partition(":")
    if kind == "user" and name:
        return name
    if kind == "agent" and name:
        return f"agent {name}"
    return actor


def _stamp(ts: str) -> datetime:
    """Event stamps have no fraction. Snapshot stamps do. Both are UTC."""
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


def when(ts: str) -> str:
    """UTC stamp shown in the local zone. Default Europe/Zurich."""
    zone = ZoneInfo(os.environ.get("ITERTHINK_TZ", "Europe/Zurich"))
    return _stamp(ts).astimezone(zone).strftime("%Y-%m-%d %H:%M")


@dataclass(frozen=True)
class _Shown:
    id: str
    message: str
    who: str
    when: str
    paths: tuple[str, ...]


def _shown(version: VersionInfo) -> _Shown:
    return _Shown(version.id, version.message, who(version.actor), when(version.ts), version.paths)


def _previous(versions: list[VersionInfo], version_id: str) -> str | None:
    ids = [item.id for item in versions]
    if version_id not in ids:
        return None
    index = ids.index(version_id) + 1
    return ids[index] if index < len(ids) else None


@dataclass(frozen=True)
class _Cell:
    text: str
    title: str


@dataclass(frozen=True)
class _Row:
    css: str
    cells: tuple[_Cell, ...]


def _text_changes(diff: FileDiff) -> tuple[list[dict[str, object]], list[str]]:
    changes: list[dict[str, object]] = []
    stable: list[str] = []
    for block in diff.blocks:
        if block.kind == "stable":
            stable.append(block.before)
            continue
        changes.append(
            {
                "index": len(changes),
                "kind": block.kind,
                "before": block.before,
                "after": block.after,
                "segments": block.segments,
            }
        )
    return changes, stable


def _cells(columns: tuple[str, ...], values: tuple[str, ...], titles: dict[str, str]) -> _Row:
    cells = []
    for index, column in enumerate(columns):
        text = values[index] if index < len(values) else ""
        cells.append(_Cell(text, titles.get(column, "")))
    return _Row("", tuple(cells))


def _changed_row(key: str, diff: FileDiff, columns: dict[str, tuple[str, str]]) -> _Row:
    values: list[str] = []
    for index, name in enumerate(diff.columns):
        if name in columns:
            values.append(columns[name][1])
        elif index == 0:
            values.append(key)
        else:
            values.append("")
    titles = {name: pair[0] for name, pair in columns.items()}
    return _cells(diff.columns, tuple(values), titles)


def _plain(css: str, values: tuple[str, ...]) -> _Row:
    return _Row(css, tuple(_Cell(value, "") for value in values))


def _table_rows(diff: FileDiff) -> tuple[_Row, ...]:
    grouped: dict[str, dict[str, tuple[str, str]]] = {}
    for change in diff.cell_changes:
        grouped.setdefault(change.row, {})[change.column] = (change.before, change.after)
    rows = [_changed_row(key, diff, columns) for key, columns in grouped.items()]
    rows.extend(_plain("added", added) for added in diff.added_rows)
    rows.extend(_plain("removed", removed) for removed in diff.removed_rows)
    return tuple(rows)


def diff_view(diff: FileDiff) -> dict[str, object]:
    """Template values for one file diff."""
    if diff.kind == "text":
        changes, stable = _text_changes(diff)
        return {"kind": "text", "summary": diff.summary, "changes": changes, "stable": stable}
    if diff.kind == "table":
        return {
            "kind": "table",
            "summary": diff.summary,
            "columns": diff.columns,
            "rows": _table_rows(diff),
        }
    if diff.kind == "model":
        rows = diff.details.get("rows", [])
        return {
            "kind": "model",
            "summary": diff.summary,
            "rows": rows if isinstance(rows, list) else [],
        }
    return {"kind": "other", "summary": diff.summary}


def _encoded(path: str) -> str:
    return quote(path, safe="")


@router.get("/p/{project_id}/panel", response_class=HTMLResponse, name="panel")
def panel(
    request: Request,
    project_id: str,
    path: str = "",
    tab: str = "history",
    bridge: Bridge = _bridge,
) -> HTMLResponse:
    chosen = tab if tab in {"history", "proposals", "log"} else "history"
    versions = [_shown(item) for item in bridge.history(project_id, path or None)]
    proposals = bridge.proposals(project_id)
    return render(
        request,
        "history/panel.html",
        project_id=project_id,
        path=path,
        path_q=_encoded(path),
        tab=chosen,
        versions=versions,
        proposals=proposals,
        open_count=len(proposals),
        entries=bridge.log(project_id),
        verify=bridge.verify(project_id),
        who=who,
        when=when,
    )


@router.get("/p/{project_id}/diff", response_class=HTMLResponse, name="diff")
def diff_page(
    request: Request,
    project_id: str,
    path: str,
    base: str | None = None,
    target: str | None = None,
    bridge: Bridge = _bridge,
) -> HTMLResponse:
    found = bridge.diff(project_id, path, base, target)
    return render(request, "history/diff.html", view=diff_view(found))


def _file_diff(bridge: Bridge, project_id: str, version_id: str, path: str) -> dict[str, object]:
    ordered = bridge.history(project_id, path)
    base = _previous(ordered, version_id)
    return {"path": path, "view": diff_view(bridge.diff(project_id, path, base, version_id))}


def _version_context(
    bridge: Bridge, project_id: str, version_id: str, path: str
) -> dict[str, object]:
    ordered = bridge.history(project_id, path or None)
    current = next(item for item in ordered if item.id == version_id)
    targets = (path,) if path else current.paths
    files = [_file_diff(bridge, project_id, version_id, item) for item in targets]
    return {
        "project_id": project_id,
        "path": path,
        "version": _shown(current),
        "files": files,
        "toast": "",
    }


@router.get("/p/{project_id}/versions/{version_id}", response_class=HTMLResponse, name="version")
def version_page(
    request: Request,
    project_id: str,
    version_id: str,
    path: str = "",
    bridge: Bridge = _bridge,
) -> HTMLResponse:
    context = _version_context(bridge, project_id, version_id, path)
    return render(request, "history/version.html", **context)


@router.post("/p/{project_id}/restore", response_class=HTMLResponse, name="restore")
def restore(
    request: Request,
    project_id: str,
    path: str = _path,
    version: str = _version_field,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> HTMLResponse:
    bridge.restore(project_id, path, version, actor)
    context = _version_context(bridge, project_id, version, path)
    context["toast"] = "Restored"
    response = render(request, "history/version.html", **context)
    response.headers["HX-Trigger"] = json.dumps({"versions-changed": {"path": path}})
    return response
