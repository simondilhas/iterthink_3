"""Checks panel. The model runs off the request, then the symbols stream."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Iterator
from html import escape

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from iterthink.services.bridge import Bridge, NotFound
from iterthink.web.app import actor_of, bridge_of
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)
_actor = Depends(actor_of)
_path = Form("")
_check = Form("")
_DONE: dict[str, str] = {}


def _call(bridge: Bridge, name: str, *args: object) -> object:
    found = getattr(bridge, name, None)
    if not callable(found):
        raise NotFound("checks are not available")
    return found(*args)


def symbols_html(result: object) -> str:
    marks = getattr(result, "symbols", ())
    rows: list[str] = []
    if isinstance(marks, tuple):
        for mark in marks:
            region = escape(str(getattr(mark, "region", "")))
            symbol = escape(str(getattr(mark, "symbol", "?")))
            finding = escape(str(getattr(mark, "finding", "")))
            rows.append(
                f'<p class="check-region" data-region="{region}">'
                f'<span class="check-mark">{symbol}</span> {finding}</p>'
            )
    sources = getattr(result, "sources", ())
    items = ""
    if isinstance(sources, tuple):
        items = "".join(f"<li>{escape(item)}</li>" for item in sources if isinstance(item, str))
    word = "advice, same version" if getattr(result, "cached", False) else "advice"
    ident = escape(str(getattr(result, "check_id", "")))
    body = "".join(rows)
    return (
        f'<check-symbols data-check="{ident}">'
        f'<p class="quiet">Check {word}</p>{body}<ul class="check-sources">{items}</ul>'
        "</check-symbols>"
    )


def _ids(bridge: Bridge, project_id: str, check: str) -> list[str]:
    if check and check != "all":
        return [check]
    found = getattr(bridge, "checks_for", None)
    if not callable(found):
        return []
    rows = found(project_id)
    if not isinstance(rows, list):
        return []
    return [str(item.id) for item in rows if getattr(item, "id", "")]


def _render(bridge: Bridge, project_id: str, path: str, check: str, actor: str) -> str:
    runner = getattr(bridge, "run_check", None)
    if not callable(runner):
        return '<p class="quiet">Checking</p>'
    idents = _ids(bridge, project_id, check)
    parts = [symbols_html(runner(project_id, path, ident, actor)) for ident in idents]
    return "".join(parts) or '<p class="quiet">No checks</p>'


def _events(token: str) -> Iterator[str]:
    for _ in range(400):
        html = _DONE.pop(token, None)
        if html is not None:
            yield f"event: message\ndata: {html}\n\n"
            yield "event: done\ndata: done\n\n"
            return
        time.sleep(0.02)
    yield "event: done\ndata: done\n\n"


def _start(bridge: Bridge, project_id: str, path: str, check: str, actor: str) -> str:
    token = secrets.token_hex(8)

    def work() -> None:
        _DONE[token] = _render(bridge, project_id, path, check, actor)

    threading.Thread(target=work, daemon=True).start()
    return token


@router.get("/p/{project_id}/checks", name="checks", response_model=None)
def checks_page(
    request: Request,
    project_id: str,
    path: str = "",
    stream: str = "",
    bridge: Bridge = _bridge,
) -> StreamingResponse | HTMLResponse:
    if stream:
        return StreamingResponse(_events(stream), media_type="text/event-stream")
    found = _call(bridge, "checks_for", project_id)
    checks = found if isinstance(found, list) else []
    return render(request, "checks/page.html", project_id=project_id, path=path, checks=checks)


@router.post("/p/{project_id}/checks", name="checks_run", response_class=HTMLResponse)
def checks_post(
    project_id: str,
    path: str = _path,
    check: str = _check,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> HTMLResponse:
    token = _start(bridge, project_id, path, check, actor)
    url = f"/p/{project_id}/checks?stream={token}"
    body = (
        f'<div hx-ext="sse" sse-connect="{url}" sse-swap="message" sse-close="done">'
        '<p class="quiet">Checking</p></div>'
    )
    return HTMLResponse(body)
