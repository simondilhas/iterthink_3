"""Start and stop dictation. The page sends no audio. Transcripts arrive over SSE."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import cast

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, StreamingResponse

from iterthink.services.bridge import Bridge, NotFound
from iterthink.web.app import bridge_of

router = APIRouter()
_bridge = Depends(bridge_of)


def _method(bridge: Bridge, name: str) -> Callable[..., object]:
    found = getattr(bridge, name, None)
    if not callable(found):
        raise NotFound("dictation is not available")
    return cast(Callable[..., object], found)


def _stream(bridge: Bridge, project_id: str) -> Iterator[str]:
    pull = _method(bridge, "dictation_events")
    events = cast(Iterator[tuple[str, str]], pull(project_id))
    for event, data in events:
        yield f"event: {event}\ndata: {data}\n\n"


def _start(bridge: Bridge, project_id: str) -> PlainTextResponse:
    _method(bridge, "dictation_start")(project_id)
    return PlainTextResponse("listening")


def _stop(bridge: Bridge, project_id: str) -> PlainTextResponse:
    _method(bridge, "dictation_stop")(project_id)
    return PlainTextResponse("stopped")


@router.post("/dictation/start", name="dictation_start_home")
def dictation_start_home(bridge: Bridge = _bridge) -> PlainTextResponse:
    return _start(bridge, "")


@router.post("/p/{project_id}/dictation/start", name="dictation_start")
def dictation_start(project_id: str, bridge: Bridge = _bridge) -> PlainTextResponse:
    return _start(bridge, project_id)


@router.post("/dictation/stop", name="dictation_stop_home")
def dictation_stop_home(bridge: Bridge = _bridge) -> PlainTextResponse:
    return _stop(bridge, "")


@router.post("/p/{project_id}/dictation/stop", name="dictation_stop")
def dictation_stop(project_id: str, bridge: Bridge = _bridge) -> PlainTextResponse:
    return _stop(bridge, project_id)


@router.get("/dictation/events", name="dictation_events_home")
def dictation_events_home(bridge: Bridge = _bridge) -> StreamingResponse:
    return StreamingResponse(_stream(bridge, ""), media_type="text/event-stream")


@router.get("/p/{project_id}/dictation/events", name="dictation_events")
def dictation_events(project_id: str, bridge: Bridge = _bridge) -> StreamingResponse:
    return StreamingResponse(_stream(bridge, project_id), media_type="text/event-stream")


@router.get("/dictation/key", name="dictation_key_home")
def dictation_key_home(bridge: Bridge = _bridge) -> PlainTextResponse:
    return PlainTextResponse(str(_method(bridge, "dictation_config")("")))


@router.get("/p/{project_id}/dictation/key", name="dictation_key")
def dictation_key(project_id: str, bridge: Bridge = _bridge) -> PlainTextResponse:
    return PlainTextResponse(str(_method(bridge, "dictation_config")(project_id)))
