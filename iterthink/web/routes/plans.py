"""A plan page with its changes drawn on top."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, Response

from iterthink.services.bridge import Bridge, NotFound
from iterthink.web.app import bridge_of
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)


def _call(bridge: Bridge, name: str, *args: object) -> object:
    found = getattr(bridge, name, None)
    if not callable(found):
        raise NotFound("plans are not available")
    return found(*args)


@router.get("/p/{project_id}/plans", response_class=HTMLResponse, name="plans")
def plans_page(
    request: Request,
    project_id: str,
    path: str = "",
    base: Annotated[str, Query(alias="from")] = "",
    target: Annotated[str, Query(alias="to")] = "",
    page: int = 1,
    view: str = "single",
    bridge: Bridge = _bridge,
) -> HTMLResponse:
    screen = _call(bridge, "plan_screen", project_id, path, base, target, page, view)
    return render(request, "plans/page.html", project_id=project_id, screen=screen)


@router.get("/p/{project_id}/plans/page", name="plans_page")
def plan_image(
    project_id: str,
    path: str = "",
    version: str = "current",
    page: int = 1,
    bridge: Bridge = _bridge,
) -> Response:
    data = _call(bridge, "plan_png", project_id, path, version, page)
    if not isinstance(data, bytes):
        raise NotFound("no page image")
    return Response(content=data, media_type="image/png")
