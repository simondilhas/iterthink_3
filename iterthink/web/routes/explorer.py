"""Workspace explorer. Projects sit above the current project's files."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from starlette.routing import compile_path

from iterthink.services.bridge import Bridge
from iterthink.web.app import bridge_of
from iterthink.web.routes.files import _sorted, _tree
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)
_workspace = Form()
_name = Form()


def _release_previous_panel() -> None:
    """A1 registered the same path. This panel is the one the Files button loads."""
    from iterthink.web.routes import files as files_routes

    for route in files_routes.router.routes:
        if not isinstance(route, APIRoute) or route.name != "explorer":
            continue
        route.path = "/p/{project_id}/files-tree"
        compiled = compile_path(route.path)
        route.path_regex, route.path_format, route.param_convertors = compiled
        route.name = "files_tree"
        files_routes.router._mark_routes_changed()
        return


_release_previous_panel()


def _panel(bridge: Bridge, project_id: str) -> object:
    finder = getattr(bridge, "explorer_panel", None)
    if not callable(finder):
        return None
    return finder(project_id)


@router.get("/p/{project_id}/explorer", response_class=HTMLResponse, name="explorer")
def explorer(request: Request, project_id: str, bridge: Bridge = _bridge) -> HTMLResponse:
    tree = _sorted(_tree(project_id, bridge.files(project_id)))
    return render(
        request,
        "explorer/panel.html",
        project_id=project_id,
        tree=tree,
        panel=_panel(bridge, project_id),
    )


@router.post("/p/{project_id}/explorer/ignore", response_class=HTMLResponse, name="explorer_ignore")
def explorer_ignore(
    request: Request,
    project_id: str,
    workspace: str = _workspace,
    name: str = _name,
    bridge: Bridge = _bridge,
) -> HTMLResponse:
    action = getattr(bridge, "workspace_ignore", None)
    if callable(action):
        action(Path(workspace), name)
    return explorer(request, project_id, bridge)
