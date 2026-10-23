"""Decision log and whether the chain still matches."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from iterthink.services.bridge import Bridge
from iterthink.web.app import bridge_of
from iterthink.web.routes.history import when, who
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)


@router.get("/p/{project_id}/log", response_class=HTMLResponse, name="log")
def log_page(request: Request, project_id: str, bridge: Bridge = _bridge) -> HTMLResponse:
    return render(
        request,
        "log/page.html",
        project_id=project_id,
        entries=bridge.log(project_id),
        verify=bridge.verify(project_id),
        who=who,
        when=when,
    )
