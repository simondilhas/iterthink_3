"""Start screen: the line. Projects and folders open from the line or the menu."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from iterthink.services.bridge import Bridge, BridgeError, ProjectInfo
from iterthink.web.app import bridge_of, templates

router = APIRouter()
_bridge = Depends(bridge_of)
_query = Form("")
_create = Form("")

_LIST_PROJECTS = re.compile(r"^(?:(?:open|show|list)\s+)?(?:(?:my|a|all)\s+)?projects?$|^open$")
_PATH = re.compile(r"^(?:/|~|[A-Za-z]:[\\/])")
_NEW_PROJECT = re.compile(
    r"^(?:new project|create(?: a)?(?: new)? project|neues projekt)(?: (?P<name>.+))?$",
    re.IGNORECASE,
)
_COLOR = re.compile(r"^#[0-9A-Fa-f]{3,8}$")
_TOKEN = {
    "page_background": "--bg",
    "on_surface": "--fg",
    "on_surface_soft": "--muted",
    "outline": "--line",
    "primary": "--accent",
    "success": "--ins-bg",
    "warning": "--warn",
    "error": "--error",
}


def theme_style(appearance: str | None = None) -> str:
    """CSS variables from the seeded theme. Appearance picks dark or light."""
    path = Path(__file__).resolve().parents[2] / "defaults" / "config.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    data = loaded if isinstance(loaded, dict) else {}
    themes = data.get("theme")
    if not isinstance(themes, dict):
        return ""
    name = "dark" if (appearance or data.get("appearance")) == "dark" else "light"
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


def _ask(request: Request, name: str, *args: object) -> object:
    """A value the bridge offers for every page, or None when it has none."""
    found = getattr(getattr(request.app.state, "bridge", None), name, None)
    if not callable(found):
        return None
    try:
        return found(*args)
    except BridgeError:
        return None


def render(request: Request, template: str, **context: object) -> HTMLResponse:
    """A full page or fragment with the shared language, theme and shortcuts."""
    appearance = _ask(request, "appearance")
    project = request.path_params.get("project_id")
    payload: dict[str, object] = {
        "lang": "en",
        "theme_style": theme_style(appearance if isinstance(appearance, str) else None),
        "shortcuts": _ask(request, "shortcut_keys", project) or {},
    }
    payload.update(context)
    return templates.TemplateResponse(request, template, payload)


@router.get("/", response_class=HTMLResponse, name="home")
def home(request: Request) -> HTMLResponse:
    return render(request, "home/index.html")


def matching_projects(projects: list[ProjectInfo], text: str) -> list[ProjectInfo]:
    """Exact name first (case-insensitive), else every project whose name contains the text."""
    wanted = text.casefold()
    exact = [p for p in projects if p.name.casefold() == wanted]
    if exact:
        return exact[:1]
    return [p for p in projects if wanted in p.name.casefold()]


def folder_page(request: Request, bridge: Bridge, raw: str) -> HTMLResponse:
    """The folder's first-level subfolders, plus the folder itself unless it is a project."""
    folder = Path(raw).expanduser().resolve()
    folders = bridge.open_folder(folder)
    is_project = len(folders) == 1 and folders[0].path == str(folder) and folders[0].project_id
    return render(
        request,
        "home/folders.html",
        folders=folders,
        folder=None if is_project else folder,
    )


def _open(request: Request, href: str) -> Response:
    if request.headers.get("HX-Request"):
        return Response(status_code=200, headers={"HX-Redirect": href})
    return RedirectResponse(href, status_code=303)


def _create_named(request: Request, name: str, bridge: Bridge) -> Response:
    info = bridge.make_project(Path(name))
    return _open(request, f"/p/{info.id}")


@router.post("/line", name="home_line", response_model=None)
def home_line(
    request: Request, q: str = _query, create: str = _create, bridge: Bridge = _bridge
) -> Response:
    """Enter on the start screen. Fixed rules first; then the local model may name a place."""
    text = " ".join(q.split())
    if create == "1":
        if not text:
            return render(request, "home/name.html")
        return _create_named(request, text, bridge)
    if _PATH.match(text):
        return folder_page(request, bridge, text)
    match = _NEW_PROJECT.match(text)
    if match:
        name = match.group("name")
        if name:
            return _create_named(request, name, bridge)
        return render(request, "home/name.html")
    projects = bridge.projects()
    if _LIST_PROJECTS.match(text.casefold()):
        return render(request, "home/projects.html", projects=projects)
    found = matching_projects(projects, text) if len(text) >= 3 else []
    if len(found) == 1:
        return _open(request, f"/p/{found[0].id}")
    if found:
        return render(request, "home/projects.html", projects=found)
    starter = getattr(bridge, "start_work", None)
    if callable(starter) and text:
        href = starter(text, request.app.state.actor)
        if isinstance(href, str):
            return _open(request, href)
    placer = getattr(bridge, "place_line", None)
    place = placer(text) if callable(placer) and text else None
    if place is not None:
        kind, target = place
        if kind == "project":
            return _open(request, target)
        return folder_page(request, bridge, target)
    return render(request, "home/hint.html")
