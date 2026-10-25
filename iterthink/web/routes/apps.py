"""Ask for a tool and open it in a sandboxed frame."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from iterthink.services.bridge import Bridge, NotFound
from iterthink.web.app import actor_of, bridge_of
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)
_actor = Depends(actor_of)
_ask = Form("")
_VENDOR = Path(__file__).resolve().parents[1] / "static" / "vendor"


def _call(bridge: Bridge, name: str, *args: object) -> object:
    found = getattr(bridge, name, None)
    if not callable(found):
        raise NotFound("apps are not available")
    return found(*args)


@router.get("/p/{project_id}/apps", response_class=HTMLResponse, name="apps")
def apps_page(request: Request, project_id: str, bridge: Bridge = _bridge) -> HTMLResponse:
    items = _call(bridge, "apps", project_id)
    return render(request, "apps/page.html", project_id=project_id, apps=items, srcdoc="", slug="")


@router.post("/p/{project_id}/apps", response_model=None)
def apps_build(
    project_id: str, ask: str = _ask, bridge: Bridge = _bridge, actor: str = _actor
) -> RedirectResponse:
    info = _call(bridge, "app_build", project_id, ask, actor)
    return RedirectResponse(f"/p/{project_id}/apps/{getattr(info, 'id', '')}", status_code=303)


@router.get("/p/{project_id}/apps/{app_id}", response_class=HTMLResponse, name="app_page")
def app_page(
    request: Request, project_id: str, app_id: str, bridge: Bridge = _bridge
) -> HTMLResponse:
    origin = str(request.base_url)
    document = _call(bridge, "app_srcdoc", project_id, app_id, origin)
    info = _call(bridge, "app_run", project_id, app_id)
    return render(
        request,
        "apps/page.html",
        project_id=project_id,
        apps=[],
        srcdoc=document if isinstance(document, str) else "",
        slug=app_id,
        title=getattr(info, "title", app_id),
    )


@router.post("/p/{project_id}/apps/{app_id}/keep", response_model=None)
def app_keep(
    project_id: str, app_id: str, bridge: Bridge = _bridge, actor: str = _actor
) -> RedirectResponse:
    _call(bridge, "app_keep", project_id, app_id, actor)
    return RedirectResponse(f"/p/{project_id}/apps/{app_id}", status_code=303)


@router.post("/p/{project_id}/apps/{app_id}/discard", response_model=None)
def app_discard(
    project_id: str, app_id: str, bridge: Bridge = _bridge, actor: str = _actor
) -> RedirectResponse:
    _call(bridge, "app_discard", project_id, app_id, actor)
    return RedirectResponse(f"/p/{project_id}/apps", status_code=303)


@router.post("/p/{project_id}/apps/{app_id}/call")
async def app_call(
    request: Request,
    project_id: str,
    app_id: str,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> JSONResponse:
    loaded = await request.json()
    body = loaded if isinstance(loaded, dict) else {}
    name = body.get("name")
    if not isinstance(name, str) or not name:
        return JSONResponse({"error": "only propose can write"})
    result = _call(bridge, "app_call", project_id, app_id, name, body.get("args"), actor)
    return JSONResponse(result)


@router.post("/p/{project_id}/apps/{app_id}/revise", response_model=None)
def app_revise(
    project_id: str,
    app_id: str,
    ask: str = _ask,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> RedirectResponse:
    _call(bridge, "app_revise", project_id, app_id, ask, actor)
    return RedirectResponse(f"/p/{project_id}/proposals", status_code=303)


@router.get("/app-vendor/{name}")
def app_vendor(name: str) -> Response:
    """Vendor bytes for a sandboxed frame. The frame's origin is opaque."""
    if "/" in name or name.startswith("."):
        raise NotFound(name)
    path = _VENDOR / name
    if not path.is_file():
        raise NotFound(name)
    return Response(
        path.read_bytes(),
        media_type="text/javascript",
        headers={"Access-Control-Allow-Origin": "null"},
    )
