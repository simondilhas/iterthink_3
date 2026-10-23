"""Keyword search under the line. Enter opens the first hit."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from iterthink.services.bridge import Bridge
from iterthink.web.app import bridge_of
from iterthink.web.routes.files import file_href
from iterthink.web.routes.home import render

router = APIRouter()
_LIMIT = 20
_bridge = Depends(bridge_of)
_query = Form("")


@dataclass(frozen=True)
class _Hit:
    path: str
    line: int
    snippet: str
    href: str


@router.get("/p/{project_id}/search", response_class=HTMLResponse, name="search")
def search(
    request: Request, project_id: str, q: str = "", bridge: Bridge = _bridge
) -> HTMLResponse:
    found = bridge.search(project_id, q, limit=_LIMIT)
    hits = [
        _Hit(hit.path, hit.line, hit.snippet, file_href(project_id, hit.path, hit.line or None))
        for hit in found
    ]
    return render(request, "search/results.html", hits=hits)


@router.post("/p/{project_id}/line", name="line", response_model=None)
def line(
    request: Request, project_id: str, q: str = _query, bridge: Bridge = _bridge
) -> HTMLResponse | RedirectResponse:
    found = bridge.search(project_id, q, limit=_LIMIT)
    if not found:
        return render(request, "search/empty.html")
    top = found[0]
    return RedirectResponse(file_href(project_id, top.path, top.line or None), status_code=303)
