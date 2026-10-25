"""File panel, rendered files, and saving the user's own edit."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from markdown_it import MarkdownIt

from iterthink.services.bridge import Bridge, FileContent, FileEntry, VersionInfo
from iterthink.web.app import actor_of, bridge_of
from iterthink.web.routes.home import render

router = APIRouter()
_MD = MarkdownIt("commonmark", {"html": False})  # raw HTML in a file stays text
_bridge = Depends(bridge_of)
_actor = Depends(actor_of)
_text = Form()


@dataclass
class _File:
    name: str
    href: str
    kind: str
    open_proposals: int


@dataclass
class _Dir:
    name: str
    dirs: dict[str, _Dir] = field(default_factory=dict)
    files: list[_File] = field(default_factory=list)


def file_href(project_id: str, path: str, line: int | None = None) -> str:
    """URL for a project file. Spaces and non-ASCII stay in the path."""
    href = f"/p/{project_id}/f/{quote(path, safe='/')}"
    if line:
        return f"{href}?line={line}"
    return href


def _tree(project_id: str, entries: list[FileEntry]) -> _Dir:
    root = _Dir("")
    for entry in sorted(entries, key=lambda item: item.path):
        node = root
        parts = entry.path.split("/")
        for part in parts[:-1]:
            node = node.dirs.setdefault(part, _Dir(part))
        node.files.append(
            _File(
                parts[-1],
                file_href(project_id, entry.path),
                entry.kind,
                entry.open_proposals,
            )
        )
    return root


def _sorted(node: _Dir) -> _Dir:
    return _Dir(
        node.name,
        {name: _sorted(node.dirs[name]) for name in sorted(node.dirs)},
        node.files,
    )


@router.get("/p/{project_id}/explorer", response_class=HTMLResponse, name="explorer")
def explorer(request: Request, project_id: str, bridge: Bridge = _bridge) -> HTMLResponse:
    tree = _sorted(_tree(project_id, bridge.files(project_id)))
    return render(request, "files/explorer.html", project_id=project_id, tree=tree)


def _marked(text: str | None, line: int | None) -> str | None:
    if not text or not line or line < 1:
        return None
    rows = text.splitlines()
    if line > len(rows):
        return None
    return rows[line - 1]


def _view(content: FileContent, editing: bool) -> dict[str, object]:
    text = content.text
    if text is None:
        return {"mode": "later", "html": "", "rows": [], "editing": False}
    if content.kind == "markdown":
        return {"mode": "markdown", "html": _MD.render(text), "rows": [], "editing": editing}
    if content.kind == "table" and not content.path.lower().endswith(".xlsx"):
        rows = list(csv.reader(io.StringIO(text)))
        return {"mode": "table", "html": "", "rows": rows, "editing": editing}
    return {"mode": "later", "html": "", "rows": [], "editing": False}


@router.get("/p/{project_id}/f/{path:path}", response_class=HTMLResponse, name="file")
def file_page(
    request: Request,
    project_id: str,
    path: str,
    edit: int = 0,
    line: int | None = None,
    bridge: Bridge = _bridge,
) -> HTMLResponse:
    content = bridge.read(project_id, path)
    return _page(request, project_id, content, bool(edit), line, "", "files/file.html")


@router.post("/p/{project_id}/f/{path:path}", response_class=HTMLResponse, name="save_file")
def save_file(
    request: Request,
    project_id: str,
    path: str,
    text: str = _text,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> HTMLResponse:
    version: VersionInfo | None = bridge.save(project_id, path, text, actor)
    content = bridge.read(project_id, path)
    toast = "Saved" if version is not None else "No changes"
    response = _page(request, project_id, content, True, None, toast, "files/body.html")
    if version is not None:
        response.headers["HX-Trigger"] = json.dumps({"versions-changed": {"path": content.path}})
    return response


def _page(
    request: Request,
    project_id: str,
    content: FileContent,
    editing: bool,
    line: int | None,
    toast: str,
    template: str,
) -> HTMLResponse:
    view = _view(content, editing)
    return render(
        request,
        template,
        project_id=project_id,
        content=content,
        action=file_href(project_id, content.path),
        marked=_marked(content.text, line),
        line=line or 0,
        toast=toast,
        **view,
    )
