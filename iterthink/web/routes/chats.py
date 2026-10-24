"""A chat page. The answer streams; the chat file is the record."""

from __future__ import annotations

import secrets
from collections.abc import Iterable, Iterator
from typing import cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from iterthink.services.bridge import Bridge, ChatInfo, ChatMessage, NotFound
from iterthink.web.app import actor_of, bridge_of
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)
_actor = Depends(actor_of)
_text = Form("")
_JOBS: dict[str, Iterator[str]] = {}


def _href(project_id: str, chat_id: str) -> str:
    return f"/p/{project_id}/chats/{quote(chat_id, safe='')}"


def _locked(bridge: Bridge, project_id: str, chat_id: str, actor: str) -> str:
    fn = getattr(bridge, "chat_locked", None)
    if not callable(fn):
        return ""
    found = cast(object, fn(project_id, chat_id, actor))
    return found if isinstance(found, str) else ""


def _keep(stream: Iterator[str]) -> str:
    token = secrets.token_hex(8)
    _JOBS[token] = stream
    return token


def _chunks(found: object) -> Iterator[str]:
    if isinstance(found, str) or not hasattr(found, "__iter__"):
        raise NotFound("that answer is no longer streaming")
    for item in cast(Iterable[object], found):
        if not isinstance(item, str):
            raise NotFound("that answer is no longer streaming")
        yield item


def _shown(chunk: str) -> str:
    return chunk.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _events(chunks: Iterator[str]) -> Iterator[str]:
    for chunk in chunks:
        body = "".join(f"data: {line}\n" for line in _shown(chunk).split("\n"))
        yield f"event: message\n{body}\n"
    yield "event: done\ndata: end\n\n"


def _refs(project_id: str, info: ChatInfo) -> list[dict[str, str]]:
    return [
        {"path": path, "href": f"/p/{project_id}/doc/{quote(path, safe='/')}"}
        for path in info.references
    ]


def _page(
    request: Request,
    project_id: str,
    info: ChatInfo,
    messages: list[ChatMessage],
    locked: str,
    toast: str,
) -> HTMLResponse:
    template = "chats/body.html" if request.headers.get("HX-Request") else "chats/page.html"
    return render(
        request,
        template,
        project_id=project_id,
        chat=info,
        messages=messages,
        references=_refs(project_id, info),
        href=_href(project_id, info.id),
        locked=locked,
        toast=toast,
    )


def _info(bridge: Bridge, project_id: str, chat_id: str) -> ChatInfo:
    for item in bridge.chats(project_id):
        if item.id == chat_id:
            return item
    raise NotFound(f"unknown chat {chat_id}")


@router.get("/p/{project_id}/chats/{chat_id}", name="chat", response_model=None)
def chat_page(
    request: Request,
    project_id: str,
    chat_id: str,
    stream: str = "",
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> HTMLResponse | StreamingResponse:
    if stream:
        found = _JOBS.pop(stream, None)
        if found is None:
            raise NotFound("that answer is no longer streaming")
        return StreamingResponse(_events(_chunks(found)), media_type="text/event-stream")
    info = _info(bridge, project_id, chat_id)
    locked = _locked(bridge, project_id, chat_id, actor)
    return _page(request, project_id, info, bridge.chat_messages(project_id, chat_id), locked, "")


@router.post("/p/{project_id}/chats/{chat_id}", name="chat_post", response_class=HTMLResponse)
def chat_post(
    request: Request,
    project_id: str,
    chat_id: str,
    text: str = _text,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> HTMLResponse:
    model = getattr(request.app.state, "chat_router", None)
    use = getattr(bridge, "use_model", None)
    if model is not None and callable(use):
        use(model)
    token = _keep(bridge.chat_send(project_id, chat_id, text, actor))
    stream = f"{_href(project_id, chat_id)}?stream={token}"
    return render(request, "chats/panel.html", stream=stream)
