"""Enter on the project line: classify, then open that surface."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.routing import APIRoute
from starlette.routing import compile_path

from iterthink.services.bridge import Bridge
from iterthink.web.app import actor_of, bridge_of
from iterthink.web.routes.files import file_href
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)
_actor = Depends(actor_of)
_query = Form("")
_mode = Form("")


def _release_previous_line() -> None:
    """A1 registered keyword Enter on this path. Classification owns it now."""
    from iterthink.web.routes import search as search_routes

    for route in search_routes.router.routes:
        if not isinstance(route, APIRoute) or route.name != "line":
            continue
        route.path = "/p/{project_id}/line-keyword"
        compiled = compile_path(route.path)
        route.path_regex, route.path_format, route.param_convertors = compiled
        route.name = "line_keyword"
        search_routes.router._mark_routes_changed()
        return


_release_previous_line()


def _keyword(
    request: Request, project_id: str, text: str, bridge: Bridge
) -> HTMLResponse | RedirectResponse:
    found = bridge.search(project_id, text, limit=20)
    if not found:
        return render(request, "search/empty.html")
    top = found[0]
    return RedirectResponse(file_href(project_id, top.path, top.line or None), status_code=303)


def _go(request: Request, href: str, body: str) -> Response:
    if request.headers.get("HX-Request"):
        response = HTMLResponse(body)
        response.headers["HX-Redirect"] = href
        return response
    return RedirectResponse(href, status_code=303)


@router.post("/p/{project_id}/line", name="line", response_model=None)
def line(
    request: Request,
    project_id: str,
    q: str = _query,
    mode: str = _mode,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> HTMLResponse | RedirectResponse | Response:
    text = " ".join(q.split())
    classify = getattr(bridge, "classify_line", None)
    opener = getattr(bridge, "open_line", None)
    if not callable(classify) or not callable(opener):
        return _keyword(request, project_id, text, bridge)
    found = classify(project_id, text, mode or None, actor)
    if found.intent.mode in {"app", "task"} and not found.reopen:
        hits = bridge.search(project_id, text, limit=20)
        return render(
            request, "line/soon.html", project_id=project_id, line=text, hits=hits, found=found
        )
    if found.intent.mode == "search" and not found.review and not found.reopen:
        hits = bridge.search(project_id, text, limit=20)
        return render(
            request, "line/results.html", project_id=project_id, line=text, hits=hits, found=found
        )
    href = opener(project_id, found, text, actor)
    label = "review" if found.review else found.intent.mode
    sure = "" if found.confidence >= 0.6 else " · not sure"
    body = f'<p class="quiet">Opened as {label}{sure} · switch</p>'
    return _go(request, href, body)
