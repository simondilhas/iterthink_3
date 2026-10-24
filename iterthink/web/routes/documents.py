"""Full-width Markdown document, margin menu, and the streamed answer."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from markdown_it import MarkdownIt

from iterthink.services.bridge import Bridge, FileDiff, NotFound, VersionInfo
from iterthink.web.app import actor_of, bridge_of
from iterthink.web.routes.history import diff_view
from iterthink.web.routes.home import render

router = APIRouter()
_MD = MarkdownIt()
_bridge = Depends(bridge_of)
_actor = Depends(actor_of)
_op = Form("")
_text = Form("")
_action = Form("")
_instruction = Form("")
_draft = Form("")
_selection = Form("")
_proposal = Form("")
_reason = Form("")
_paragraph = Form(-1)
_offset = Form(-1)


def _href(project_id: str, path: str) -> str:
    return f"/p/{project_id}/doc/{quote(path, safe='/')}"


def _call(bridge: Bridge, name: str, *args: object, **kwargs: object) -> object:
    fn = getattr(bridge, name, None)
    if not callable(fn):
        raise NotFound("documents are not available")
    return cast(object, fn(*args, **kwargs))


def _mapping(bridge: Bridge, project_id: str, path: str) -> dict[str, object]:
    found = _call(bridge, "doc_context", project_id, path)
    if not isinstance(found, dict):
        raise NotFound("documents are not available")
    return {str(key): value for key, value in found.items()}


def _groups(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    return []


def _diff(change: object) -> dict[str, object] | None:
    if not isinstance(change, dict):
        return None
    diff = change.get("diff")
    if not isinstance(diff, FileDiff):
        return None
    return diff_view(diff)


def _page(request: Request, project_id: str, path: str, bridge: Bridge, toast: str) -> HTMLResponse:
    ctx = _mapping(bridge, project_id, path)
    text = ctx.get("text")
    body = text if isinstance(text, str) else ""
    shown = ctx.get("path")
    template = "documents/body.html" if request.headers.get("HX-Request") else "documents/page.html"
    return render(
        request,
        template,
        project_id=project_id,
        path=shown if isinstance(shown, str) else path,
        href=_href(project_id, path),
        text=body,
        html=_MD.render(body),
        groups=_groups(ctx.get("groups")),
        change=ctx.get("change"),
        view=_diff(ctx.get("change")),
        toast=toast,
    )


def _model(request: Request, bridge: Bridge, project_id: str) -> object:
    found = getattr(request.app.state, "doc_router", None)
    if found is not None:
        return found
    return _call(bridge, "doc_router", project_id)


def _margin(
    request: Request,
    project_id: str,
    path: str,
    bridge: Bridge,
    actor: str,
    action_id: str,
    instruction: str,
    draft: str,
    selection: str,
    paragraph: int,
    offset: int,
) -> HTMLResponse:
    token = _call(
        bridge,
        "doc_begin",
        project_id,
        path,
        paragraph=paragraph,
        offset=offset,
        selection=selection,
        action_id=action_id,
        instruction=instruction,
        draft=draft,
        router=_model(request, bridge, project_id),
        actor=actor,
    )
    if not isinstance(token, str):
        raise NotFound("documents are not available")
    stream = f"{_href(project_id, path)}?stream={token}"
    return render(request, "documents/panel.html", stream=stream)


def _chunks(found: object) -> Iterator[str]:
    if isinstance(found, str) or not hasattr(found, "__iter__"):
        raise NotFound("that answer is no longer streaming")
    for item in cast(Iterable[object], found):
        if not isinstance(item, str):
            raise NotFound("that answer is no longer streaming")
        yield item


def _events(chunks: Iterator[str]) -> Iterator[str]:
    for chunk in chunks:
        body = "".join(f"data: {line}\n" for line in chunk.split("\n"))
        yield f"event: message\n{body}\n"
    yield "event: done\ndata: end\n\n"


def _saved(response: HTMLResponse, path: str, version: VersionInfo | None) -> HTMLResponse:
    if version is not None:
        response.headers["HX-Trigger"] = json.dumps({"versions-changed": {"path": path}})
    return response


@router.get("/p/{project_id}/doc/{path:path}", name="document", response_model=None)
def document_page(
    request: Request,
    project_id: str,
    path: str,
    stream: str = "",
    bridge: Bridge = _bridge,
) -> HTMLResponse | StreamingResponse:
    if stream:
        chunks = _chunks(_call(bridge, "doc_take", stream))
        return StreamingResponse(_events(chunks), media_type="text/event-stream")
    return _page(request, project_id, path, bridge, "")


@router.post("/p/{project_id}/doc/{path:path}", name="document_post", response_class=HTMLResponse)
def document_post(
    request: Request,
    project_id: str,
    path: str,
    op: str = _op,
    text: str = _text,
    action_id: str = _action,
    instruction: str = _instruction,
    draft: str = _draft,
    selection: str = _selection,
    proposal: str = _proposal,
    reason: str = _reason,
    paragraph: int = _paragraph,
    offset: int = _offset,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> HTMLResponse:
    if op == "margin":
        return _margin(
            request,
            project_id,
            path,
            bridge,
            actor,
            action_id,
            instruction,
            draft,
            selection,
            paragraph,
            offset,
        )
    if op == "accept":
        made = bridge.accept(project_id, proposal, actor, reason)
        return _saved(_page(request, project_id, path, bridge, "Accepted"), path, made)
    if op == "reject":
        bridge.reject(project_id, proposal, actor, reason)
        return _page(request, project_id, path, bridge, "Rejected")
    version = bridge.save(project_id, path, text, actor)
    toast = "Saved" if version is not None else "No changes"
    return _saved(_page(request, project_id, path, bridge, toast), path, version)
