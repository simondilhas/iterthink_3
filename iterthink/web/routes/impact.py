"""Check impact for a proposal. The model runs off the request, then SSE."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Iterator
from html import escape

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, StreamingResponse

from iterthink.services.bridge import Bridge
from iterthink.web.app import actor_of, bridge_of

router = APIRouter()
_bridge = Depends(bridge_of)
_actor = Depends(actor_of)
_DONE: dict[str, str] = {}


def advice_html(advice: object) -> str:
    affected = getattr(advice, "affected", ())
    paths = affected if isinstance(affected, tuple) else ()
    files = "".join(f"<li>{escape(path)}</li>" for path in paths if isinstance(path, str))
    suggestion = getattr(advice, "suggestion", "")
    label = suggestion if isinstance(suggestion, str) else ""
    word = "cached" if getattr(advice, "cached", False) else "advice"
    return f'<p class="quiet">Impact {word}: {escape(label)}</p><ul>{files}</ul>'


def _events(token: str) -> Iterator[str]:
    for _ in range(250):
        html = _DONE.pop(token, None)
        if html is not None:
            yield f"event: message\ndata: {html}\n\n"
            yield "event: done\ndata: done\n\n"
            return
        time.sleep(0.02)
    yield "event: done\ndata: done\n\n"


def _start(bridge: Bridge, project_id: str, proposal_id: str, actor: str) -> str:
    token = secrets.token_hex(8)
    runner = getattr(bridge, "impact_advice", None)

    def work() -> None:
        if not callable(runner):
            _DONE[token] = '<p class="quiet">Check impact</p>'
            return
        advice = runner(project_id, proposal_id, actor)
        _DONE[token] = advice_html(advice)

    threading.Thread(target=work, daemon=True).start()
    return token


@router.post(
    "/p/{project_id}/proposals/{proposal_id}/impact",
    name="impact",
    response_class=HTMLResponse,
)
def impact_post(
    project_id: str,
    proposal_id: str,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> HTMLResponse:
    token = _start(bridge, project_id, proposal_id, actor)
    url = f"/p/{project_id}/proposals/{proposal_id}/impact?stream={token}"
    body = (
        f'<div hx-ext="sse" sse-connect="{url}" sse-swap="message" sse-close="done">'
        '<p class="quiet">Checking impact</p></div>'
    )
    return HTMLResponse(body)


@router.get(
    "/p/{project_id}/proposals/{proposal_id}/impact",
    name="impact_stream",
    response_model=None,
)
def impact_stream(
    project_id: str, proposal_id: str, stream: str = ""
) -> StreamingResponse | HTMLResponse:
    del project_id, proposal_id
    if not stream:
        return HTMLResponse('<p class="quiet">Check impact</p>')
    return StreamingResponse(_events(stream), media_type="text/event-stream")
