"""The Settings page: every section on one page, each control saves on change."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse

from iterthink.services.bridge import Bridge, BridgeError, Invalid
from iterthink.web.app import actor_of, bridge_of
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)
_actor = Depends(actor_of)
_key = Form("")
_value = Form("")
_level = Form("")
_scope_level = Form("")
_project = Form("")
_clear = Form("")
_name = Form("")
_text = Form("")
_file_level = Form("")
_index_project = Form("")
_query_name = Query("")
_query_level = Query("workspace")
_query_project = Query("")


def _call(bridge: Bridge, name: str, *args: object) -> Any:
    found = getattr(bridge, name, None)
    if not callable(found):
        raise Invalid("settings are not available")
    return found(*args)


def window(
    request: Request, bridge: Bridge, project_id: str | None, **context: object
) -> HTMLResponse:
    """The whole page, for the start screen (no project) or one project."""
    found = getattr(bridge, "settings_sections", None)
    sections = found(project_id) if callable(found) else []
    return render(
        request, "settings/window.html", project_id=project_id, sections=sections, **context
    )


@router.get("/settings", response_class=HTMLResponse, name="settings_home")
def settings_home(request: Request, bridge: Bridge = _bridge) -> HTMLResponse:
    return window(request, bridge, None)


@router.post("/settings/set", response_class=HTMLResponse, name="settings_set")
def settings_set(
    request: Request,
    key: str = _key,
    value: str = _value,
    level: str = _level,
    scope_level: str = _scope_level,
    project: str = _project,
    clear: str = _clear,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> HTMLResponse:
    chosen = scope_level or level or ("project" if project else "workspace")
    if clear:
        row = _call(bridge, "clear_window_setting", project or None, key, chosen, actor)
    else:
        row = _call(bridge, "set_window_setting", project or None, key, value, chosen, actor)
    response = render(request, "settings/row.html", row=row, project_id=project or None)
    if key == "appearance":
        response.headers["HX-Refresh"] = "true"
    return response


@router.get("/settings/ollama", response_class=HTMLResponse, name="settings_ollama")
def settings_ollama(request: Request, bridge: Bridge = _bridge) -> HTMLResponse:
    return render(request, "settings/ollama.html", status=_call(bridge, "ollama_status"))


def _file(
    request: Request, project: str, name: str, level: str, text: str, message: str, ok: bool
) -> HTMLResponse:
    return render(
        request,
        "settings/file.html",
        project_id=project or None,
        name=name,
        level=level,
        text=text,
        message=message,
        ok=ok,
    )


@router.get("/settings/file", response_class=HTMLResponse, name="settings_file")
def settings_file(
    request: Request,
    name: str = _query_name,
    level: str = _query_level,
    project: str = _query_project,
    bridge: Bridge = _bridge,
) -> HTMLResponse:
    text = _call(bridge, "settings_file", project or None, name, level)
    return _file(request, project, name, level, str(text), "", True)


@router.post("/settings/file", response_class=HTMLResponse, name="settings_file_save")
def settings_file_save(
    request: Request,
    name: str = _name,
    level: str = _file_level,
    text: str = _text,
    project: str = _project,
    bridge: Bridge = _bridge,
) -> HTMLResponse:
    try:
        _call(bridge, "save_settings_file", project or None, name, level, text)
    except BridgeError as error:
        return _file(request, project, name, level, text, str(error), False)
    return _file(request, project, name, level, text, "Saved", True)


@router.post("/settings/index", response_class=HTMLResponse, name="settings_index")
def settings_index(
    request: Request, project: str = _index_project, bridge: Bridge = _bridge
) -> HTMLResponse:
    index = _call(bridge, "index_rebuild", project)
    return render(request, "settings/index.html", project_id=project, index=index, notice="Rebuilt")
