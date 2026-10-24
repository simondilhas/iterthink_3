"""The egress switch. The rest of settings is a later slice."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from iterthink.services.bridge import Bridge, Egress, Invalid
from iterthink.web.app import actor_of, bridge_of
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)
_actor = Depends(actor_of)
_egress = Form()
_VALUES = {"none", "shielded", "allowed"}


def _current(bridge: Bridge, project_id: str) -> str:
    bridge.files(project_id)
    for item in bridge.projects():
        if item.id == project_id:
            return item.egress
    return "shielded"


@router.get("/p/{project_id}/settings", response_class=HTMLResponse, name="settings")
def settings_page(request: Request, project_id: str, bridge: Bridge = _bridge) -> HTMLResponse:
    return render(
        request,
        "settings/page.html",
        project_id=project_id,
        egress=_current(bridge, project_id),
        notice="",
    )


@router.post("/p/{project_id}/settings", response_class=HTMLResponse, name="settings_post")
def settings_post(
    request: Request,
    project_id: str,
    egress: str = _egress,
    actor: str = _actor,
    bridge: Bridge = _bridge,
) -> HTMLResponse:
    if egress not in _VALUES:
        raise Invalid("egress is none, shielded or allowed")
    info = bridge.set_egress(project_id, cast(Egress, egress), actor)
    return render(
        request,
        "settings/page.html",
        project_id=project_id,
        egress=info.egress,
        notice="Saved.",
    )
