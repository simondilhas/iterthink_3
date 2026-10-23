"""Start screen: the line, opened projects, and opening a folder."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from iterthink.services.bridge import Bridge, ProjectInfo
from iterthink.web.app import bridge_of, templates

router = APIRouter()
_bridge = Depends(bridge_of)

_COLOR = re.compile(r"^#[0-9A-Fa-f]{3,8}$")
_TOKEN = {
    "page_background": "--bg",
    "on_surface": "--fg",
    "on_surface_soft": "--muted",
    "outline": "--line",
    "primary": "--accent",
    "success": "--ins-bg",
}


def theme_style() -> str:
    """CSS variables from the seeded theme. Appearance picks dark or light."""
    path = Path(__file__).resolve().parents[2] / "defaults" / "config.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    data = loaded if isinstance(loaded, dict) else {}
    themes = data.get("theme")
    if not isinstance(themes, dict):
        return ""
    name = "dark" if data.get("appearance") == "dark" else "light"
    palette = themes.get(name)
    if not isinstance(palette, dict):
        return ""
    rules: list[str] = []
    for key, value in palette.items():
        if not isinstance(key, str) or not isinstance(value, str) or not _COLOR.match(value):
            continue
        rules.append(f"--theme-{key.replace('_', '-')}: {value};")
        token = _TOKEN.get(key)
        if token:
            rules.append(f"{token}: {value};")
    if not rules:
        return ""
    return "<style>:root{" + "".join(rules) + "}</style>"


def render(request: Request, template: str, **context: object) -> HTMLResponse:
    """A full page or fragment with the shared language and theme."""
    payload: dict[str, object] = {"lang": "en", "theme_style": theme_style()}
    payload.update(context)
    return templates.TemplateResponse(request, template, payload)


@router.get("/", response_class=HTMLResponse, name="home")
def home(request: Request, bridge: Bridge = _bridge) -> HTMLResponse:
    projects: list[ProjectInfo] = bridge.projects()
    return render(request, "home/index.html", projects=projects)
