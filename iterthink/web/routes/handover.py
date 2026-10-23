"""Hand a project to an archive folder or to a client bundle."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from iterthink.services.bridge import Bridge, HandoverMode, Invalid
from iterthink.web.app import bridge_of
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)
_mode = Form()
_target = Form()


@router.get("/p/{project_id}/handover", response_class=HTMLResponse, name="handover")
def handover_page(request: Request, project_id: str, bridge: Bridge = _bridge) -> HTMLResponse:
    bridge.files(project_id)
    return render(request, "handover/page.html", project_id=project_id, handed="")


@router.post("/p/{project_id}/handover", response_class=HTMLResponse, name="handover_post")
def handover_post(
    request: Request,
    project_id: str,
    mode: str = _mode,
    target: str = _target,
    bridge: Bridge = _bridge,
) -> HTMLResponse:
    if mode not in {"full", "client"}:
        raise Invalid("handover is full or client")
    handed = bridge.handover(project_id, cast(HandoverMode, mode), Path(target))
    return render(request, "handover/page.html", project_id=project_id, handed=str(handed))
