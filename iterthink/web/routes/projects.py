"""Open a folder, make it a project, and show the project overview."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from iterthink.services.bridge import Bridge, FileEntry
from iterthink.web.app import bridge_of
from iterthink.web.routes.home import folder_page, render

router = APIRouter()
_bridge = Depends(bridge_of)
_path = Form()


@router.post("/open", response_class=HTMLResponse, name="open_folder")
def open_folder(request: Request, path: str = _path, bridge: Bridge = _bridge) -> HTMLResponse:
    return folder_page(request, bridge, path)


@router.post("/projects", name="make_project")
def make_project(path: str = _path, bridge: Bridge = _bridge) -> RedirectResponse:
    info = bridge.make_project(Path(path))
    return RedirectResponse(f"/p/{info.id}", status_code=303)


def _counts(entries: list[FileEntry]) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter(entry.kind for entry in entries)
    return sorted(counts.items())


def _log_break(bridge: Bridge, project_id: str) -> str:
    notice = getattr(bridge, "log_break", None)
    if not callable(notice):
        return ""
    text = notice(project_id)
    return text if isinstance(text, str) else ""


@router.get("/p/{project_id}", response_class=HTMLResponse, name="project")
def project(request: Request, project_id: str, bridge: Bridge = _bridge) -> HTMLResponse:
    message = _log_break(bridge, project_id)
    counts = _counts(bridge.files(project_id))
    waiting = bool(bridge.proposals(project_id))
    return render(
        request,
        "project/page.html",
        project_id=project_id,
        counts=counts,
        log_break=message,
        waiting=waiting,
    )
