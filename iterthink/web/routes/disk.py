"""SSE notice when a file changes outside iterthink."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from iterthink.services.bridge import Bridge, NotFound
from iterthink.web.app import bridge_of
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)


def _frame(html: str) -> str:
    body = "".join(f"data: {line}\n" for line in html.splitlines())
    return f"event: disk\n{body}\n"


def _html(request: Request, message: str) -> str:
    page = render(request, "project/_disk_changed.html", message=message)
    raw = page.body
    return raw.decode() if isinstance(raw, bytes) else bytes(raw).decode()


def _stream(request: Request, pull: Callable[[], str]) -> Iterator[str]:
    while True:
        yield _frame(_html(request, pull()))


@router.get("/p/{project_id}/disk", name="disk")
def disk(request: Request, project_id: str, bridge: Bridge = _bridge) -> StreamingResponse:
    pull = getattr(bridge, "disk_pull", None)
    if not callable(pull):
        raise NotFound(f"unknown project {project_id}")
    source = pull(project_id)
    if not callable(source):
        raise NotFound(f"unknown project {project_id}")
    return StreamingResponse(_stream(request, source), media_type="text/event-stream")
