"""Settings: the egress switch and the inherited values."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from iterthink.services.bridge import Bridge, Egress, Invalid, SettingInfo
from iterthink.web.app import actor_of, bridge_of
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)
_actor = Depends(actor_of)
_egress = Form("")
_key = Form("")
_value = Form("")
_level = Form("project")
_choice = Form("")
_file = Form("")
_VALUES = {"none", "shielded", "allowed"}


def _current(bridge: Bridge, project_id: str) -> str:
    bridge.files(project_id)
    for item in bridge.projects():
        if item.id == project_id:
            return item.egress
    return "shielded"


def _rows(bridge: Bridge, project_id: str) -> list[SettingInfo]:
    listed = getattr(bridge, "settings", None)
    if not callable(listed):
        return []
    rows = listed(project_id)
    return rows if isinstance(rows, list) else []


def _questions(bridge: Bridge, project_id: str) -> list[object]:
    pending = getattr(bridge, "pending_upgrades", None)
    if not callable(pending):
        return []
    found = pending(project_id)
    return found if isinstance(found, list) else []


def _page(
    request: Request, project_id: str, bridge: Bridge, egress: str, notice: str
) -> HTMLResponse:
    return render(
        request,
        "settings/page.html",
        project_id=project_id,
        egress=egress,
        notice=notice,
        rows=_rows(bridge, project_id),
        questions=_questions(bridge, project_id),
    )


@router.get("/p/{project_id}/settings", response_class=HTMLResponse, name="settings")
def settings_page(request: Request, project_id: str, bridge: Bridge = _bridge) -> HTMLResponse:
    return _page(request, project_id, bridge, _current(bridge, project_id), "")


@router.post("/p/{project_id}/settings", response_class=HTMLResponse, name="settings_post")
def settings_post(
    request: Request,
    project_id: str,
    egress: str = _egress,
    key: str = _key,
    value: str = _value,
    level: str = _level,
    choice: str = _choice,
    file: str = _file,
    actor: str = _actor,
    bridge: Bridge = _bridge,
) -> HTMLResponse:
    current = _apply(bridge, project_id, egress, key, value, level, choice, file, actor)
    notice = "Saved." if egress or key or choice else ""
    return _page(request, project_id, bridge, current, notice)


def _apply(
    bridge: Bridge,
    project_id: str,
    egress: str,
    key: str,
    value: str,
    level: str,
    choice: str,
    file: str,
    actor: str,
) -> str:
    current = _current(bridge, project_id)
    if choice:
        _choose(bridge, project_id, file, key, choice)
        return current
    if egress:
        if egress not in _VALUES:
            raise Invalid("egress is none, shielded or allowed")
        current = bridge.set_egress(project_id, cast(Egress, egress), actor).egress
    if key:
        _save(bridge, project_id, key, value, level, actor)
    return current


def _choose(bridge: Bridge, project_id: str, file: str, key: str, choice: str) -> None:
    resolver = getattr(bridge, "resolve_upgrade", None)
    if not callable(resolver):
        raise Invalid("settings are not available")
    resolver(project_id, file, key, choice)


def _save(bridge: Bridge, project_id: str, key: str, value: str, level: str, actor: str) -> None:
    setter = getattr(bridge, "set_setting", None)
    if not callable(setter):
        raise Invalid("settings are not available")
    setter(project_id, key, value, level, actor)
