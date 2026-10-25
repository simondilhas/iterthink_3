"""Two-step erase. The second step is the one that removes the content."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from iterthink.services.bridge import Bridge, Invalid, NotFound
from iterthink.web.app import actor_of, bridge_of
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)
_actor = Depends(actor_of)
_version = Form()
_reason = Form()
_confirm = Form("")


def _call(bridge: Bridge, name: str, *args: object) -> object:
    found = getattr(bridge, name, None)
    if not callable(found):
        raise NotFound("erase is not available")
    return found(*args)


@router.get("/p/{project_id}/erase", response_class=HTMLResponse, name="erase")
def erase_page(request: Request, project_id: str, bridge: Bridge = _bridge) -> HTMLResponse:
    bridge.files(project_id)
    return _show(request, project_id, "start", "", "")


@router.post("/p/{project_id}/erase", response_class=HTMLResponse, name="erase_post")
def erase_post(
    request: Request,
    project_id: str,
    version: str = _version,
    reason: str = _reason,
    confirm: str = _confirm,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> HTMLResponse:
    if confirm != "yes":
        if not reason.strip() or not version.strip():
            raise Invalid("erase needs a reason")
        return _show(request, project_id, "confirm", version.strip(), reason.strip())
    _call(bridge, "erase", project_id, [version.strip()], reason, True, actor)
    return _show(request, project_id, "done", "", "")


def _show(request: Request, project_id: str, step: str, version: str, reason: str) -> HTMLResponse:
    return render(
        request,
        "erase/page.html",
        project_id=project_id,
        step=step,
        version=version,
        reason=reason,
    )
