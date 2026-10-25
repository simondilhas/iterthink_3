"""Receive a file, or make the open working copy."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from iterthink.services.bridge import Bridge, NotFound
from iterthink.web.app import actor_of, bridge_of
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)
_actor = Depends(actor_of)
_path = Form()
_folder = Form("")
_upload = File()


def _call(bridge: Bridge, name: str, *args: object) -> object:
    found = getattr(bridge, name, None)
    if not callable(found):
        raise NotFound("import is not available")
    return found(*args)


@router.get("/p/{project_id}/incoming", response_class=HTMLResponse, name="incoming")
def incoming_page(request: Request, project_id: str, bridge: Bridge = _bridge) -> HTMLResponse:
    bridge.files(project_id)
    return _page(request, project_id, "", "")


@router.post("/p/{project_id}/incoming", response_class=HTMLResponse, name="incoming_work")
def incoming_work(
    request: Request,
    project_id: str,
    path: str = _path,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> HTMLResponse:
    worked = _call(bridge, "work_on", project_id, path, actor)
    return _page(request, project_id, path, worked)


@router.post("/p/{project_id}/incoming/drop", response_model=None, name="incoming_drop")
async def incoming_drop(
    request: Request,
    project_id: str,
    file: UploadFile = _upload,
    folder: str = _folder,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> Response:
    data = await file.read()
    name = file.filename or "upload"
    dropped = _call(bridge, "drop_file", project_id, name, data, actor, folder or None)
    if getattr(dropped, "placed", False):
        return RedirectResponse(str(getattr(dropped, "review", "/")), status_code=303)
    return _page(request, project_id, name, None, ask=name)


def _page(
    request: Request,
    project_id: str,
    path: str,
    worked: object,
    ask: str = "",
) -> HTMLResponse:
    return render(
        request,
        "incoming/page.html",
        project_id=project_id,
        path=path,
        worked=worked,
        ask=ask,
    )
