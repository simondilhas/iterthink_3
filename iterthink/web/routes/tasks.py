"""The task board. Columns, handover, answers and running again."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from iterthink.services.bridge import Bridge, NotFound
from iterthink.web.app import actor_of, bridge_of
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)
_actor = Depends(actor_of)
_text = Form("")
_COLUMNS = (
    ("backlog", "Backlog"),
    ("ready", "Ready"),
    ("running", "Running"),
    ("needs-input", "Needs input"),
    ("review", "Review"),
    ("done", "Done"),
    ("rejected", "Rejected"),
    ("cancelled", "Cancelled"),
)


def _call(bridge: Bridge, name: str, *args: object) -> object:
    found = getattr(bridge, name, None)
    if not callable(found):
        raise NotFound("tasks are not available")
    return found(*args)


def _page(request: Request, project_id: str, bridge: Bridge) -> HTMLResponse:
    cards = _call(bridge, "task_board", project_id)
    rows = cards if isinstance(cards, list) else []
    columns = [
        {"id": key, "label": label, "cards": [card for card in rows if card.status == key]}
        for key, label in _COLUMNS
    ]
    return render(request, "tasks/page.html", project_id=project_id, columns=columns)


@router.get("/p/{project_id}/tasks", response_class=HTMLResponse, name="tasks")
def tasks_page(request: Request, project_id: str, bridge: Bridge = _bridge) -> HTMLResponse:
    return _page(request, project_id, bridge)


@router.post("/p/{project_id}/tasks/{task_id}/ready", response_model=None)
def task_ready(
    request: Request, project_id: str, task_id: str, bridge: Bridge = _bridge, actor: str = _actor
) -> Response:
    _call(bridge, "task_ready", project_id, task_id, actor)
    return _back(request, project_id, bridge)


@router.post("/p/{project_id}/tasks/{task_id}/answer", response_model=None)
def task_answer(
    request: Request,
    project_id: str,
    task_id: str,
    text: str = _text,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> Response:
    _call(bridge, "task_answer", project_id, task_id, text, actor)
    return _back(request, project_id, bridge)


@router.post("/p/{project_id}/tasks/{task_id}/again", response_model=None)
def task_again(
    request: Request, project_id: str, task_id: str, bridge: Bridge = _bridge, actor: str = _actor
) -> Response:
    _call(bridge, "task_run_again", project_id, task_id, actor)
    return _back(request, project_id, bridge)


@router.post("/p/{project_id}/tasks/{task_id}/accept", response_model=None)
def task_accept(
    request: Request, project_id: str, task_id: str, bridge: Bridge = _bridge, actor: str = _actor
) -> Response:
    _call(bridge, "task_accept_delivery", project_id, task_id, actor)
    return _back(request, project_id, bridge)


@router.post("/p/{project_id}/tasks/{task_id}/reject", response_model=None)
def task_reject(
    request: Request,
    project_id: str,
    task_id: str,
    text: str = _text,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> Response:
    _call(bridge, "task_reject", project_id, task_id, actor, text)
    return _back(request, project_id, bridge)


@router.get("/p/{project_id}/tasks/{task_id}/events")
def task_events(project_id: str, task_id: str, bridge: Bridge = _bridge) -> Response:
    cards = _call(bridge, "task_board", project_id)
    rows = cards if isinstance(cards, list) else []
    found = next((card for card in rows if card.id == task_id), None)
    progress = found.progress if found is not None else ""
    body = f"event: progress\ndata: {progress}\n\n"
    return Response(body, media_type="text/event-stream")


def _back(request: Request, project_id: str, bridge: Bridge) -> Response:
    if request.headers.get("HX-Request"):
        return _page(request, project_id, bridge)
    return RedirectResponse(f"/p/{project_id}/tasks", status_code=303)
