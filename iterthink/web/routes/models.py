"""Compare two versions of a model. The table is read-only; large models stream progress."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Annotated, Any, Literal, cast
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from iterthink.services.bridge import Bridge, BridgeError, FileDiff, NotFound
from iterthink.web.app import bridge_of
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)
_SORTS = ("guid", "class", "storey", "path")
_CATEGORIES = ("added", "removed", "reshaped", "moved", "props_only", "unchanged")
_PARTS = ("before", "after", "diff")
Part = Literal["before", "after", "diff"]
_BACKGROUND_BYTES = 50 * 1024 * 1024
_TICK = 0.5


def _mapping(diff: FileDiff, key: str) -> dict[str, Any]:
    raw = diff.details.get(key, {})
    return cast(dict[str, Any], raw) if isinstance(raw, dict) else {}


def _all_rows(diff: FileDiff) -> list[dict[str, Any]]:
    raw = diff.details.get("rows", [])
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def _keep(row: dict[str, Any], category: str, ifc_class: str, storey: str, pset: str) -> bool:
    path = str(row.get("path", ""))
    if category and row.get("category") != category:
        return False
    if ifc_class and row.get("class") != ifc_class:
        return False
    if storey and row.get("storey") != storey:
        return False
    own = path.startswith(f"{pset}.") or path.startswith(f"type.{pset}.")
    return not pset or own


def _elements(diff: FileDiff) -> list[dict[str, Any]]:
    raw = diff.details.get("elements", [])
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _table(diff: FileDiff, rows: list[dict[str, Any]]) -> dict[str, object]:
    return {"kind": "model", "summary": diff.summary, "rows": rows}


@router.get("/p/{project_id}/models/compare", response_class=HTMLResponse, name="models_compare")
def models_compare(
    request: Request,
    project_id: str,
    path: str = "",
    base: Annotated[str, Query(alias="from")] = "",
    target: Annotated[str, Query(alias="to")] = "",
    category: str = "",
    ifc_class: Annotated[str, Query(alias="class")] = "",
    storey: str = "",
    pset: str = "",
    sort: str = "guid",
    bridge: Bridge = _bridge,
) -> HTMLResponse:
    chosen = sort if sort in _SORTS else "guid"
    page: dict[str, object] = {
        "project_id": project_id,
        "path": path,
        "base": base,
        "target": target,
        "category": category,
        "ifc_class": ifc_class,
        "storey": storey,
        "pset": pset,
        "sort": chosen,
        "categories": _CATEGORIES,
    }
    if not request.headers.get("HX-Request") and _large(bridge, project_id, path):
        query = urlencode({"path": path, "from": base, "to": target})
        events = f"/p/{project_id}/models/compare/events?{query}"
        empty = {"kind": "model", "summary": "", "rows": []}
        return render(
            request, "models/page.html", counts={}, glb={}, table=empty, events=events, **page
        )
    diff = bridge.diff(project_id, path, base or None, target or None)
    rows = [row for row in _all_rows(diff) if _keep(row, category, ifc_class, storey, pset)]
    rows.sort(key=lambda row: str(row.get(chosen, "")))
    table = _table(diff, rows)
    if request.headers.get("HX-Request"):
        return render(request, "models/table.html", table=table)
    counts = _mapping(diff, "counts")
    glb = _mapping(diff, "glb")
    return render(request, "models/page.html", counts=counts, glb=glb, table=table, **page)


def _large(bridge: Bridge, project_id: str, path: str) -> bool:
    size = next((entry.size for entry in bridge.files(project_id) if entry.path == path), 0)
    return size > _BACKGROUND_BYTES


def _frame(event: str, html: str) -> str:
    body = "".join(f"data: {line}\n" for line in html.splitlines()) or "data: \n"
    return f"event: {event}\n{body}\n"


def _html(request: Request, template: str, **context: object) -> str:
    raw = render(request, template, **context).body
    return raw.decode() if isinstance(raw, bytes) else bytes(raw).decode()


def _diff_in_background(
    bridge: Bridge, project_id: str, path: str, base: str | None, target: str | None
) -> tuple[threading.Event, dict[str, object]]:
    finished = threading.Event()
    box: dict[str, object] = {}

    def run() -> None:
        try:
            box["diff"] = bridge.diff(project_id, path, base, target)
        except BridgeError as exc:
            box["error"] = str(exc)
        finally:
            finished.set()

    threading.Thread(target=run, name="model-diff", daemon=True).start()
    return finished, box


def _progress_stream(
    request: Request, bridge: Bridge, project_id: str, path: str, base: str, target: str
) -> Iterator[str]:
    finished, box = _diff_in_background(bridge, project_id, path, base or None, target or None)

    def progress() -> str:
        counts = bridge.diff_progress(project_id, path, base or None, target or None)
        return _frame("progress", _html(request, "models/progress.html", counts=counts))

    while not finished.wait(_TICK):
        yield progress()
    yield progress()
    diff = box.get("diff")
    if isinstance(diff, FileDiff):
        rows = sorted(_all_rows(diff), key=lambda row: str(row.get("guid", "")))
        yield _frame("table", _html(request, "models/table.html", table=_table(diff, rows)))
        context = {"project_id": project_id, "path": path, "base": base, "target": target}
        glb = _mapping(diff, "glb")
        viewer = _html(request, "models/viewer.html", glb=glb, categories=_CATEGORIES, **context)
        yield _frame("viewer", viewer)
    else:
        message = str(box.get("error", "The comparison failed."))
        yield _frame("progress", _html(request, "models/progress.html", counts={}, error=message))
    yield "event: done\ndata: done\n\n"


@router.get("/p/{project_id}/models/compare/events", name="models_events")
def models_events(
    request: Request,
    project_id: str,
    path: str = "",
    base: Annotated[str, Query(alias="from")] = "",
    target: Annotated[str, Query(alias="to")] = "",
    bridge: Bridge = _bridge,
) -> StreamingResponse:
    stream = _progress_stream(request, bridge, project_id, path, base, target)
    return StreamingResponse(stream, media_type="text/event-stream")


@router.get("/p/{project_id}/models/changes.json", name="models_changes")
def models_changes(
    project_id: str,
    path: str = "",
    base: Annotated[str, Query(alias="from")] = "",
    target: Annotated[str, Query(alias="to")] = "",
    bridge: Bridge = _bridge,
) -> JSONResponse:
    diff = bridge.diff(project_id, path, base or None, target or None)
    keys = ("guid", "class", "name", "storey", "category")
    return JSONResponse([{key: item.get(key) for key in keys} for item in _elements(diff)])


@router.get("/p/{project_id}/models/glb/{key}/{part}.glb", name="models_glb")
def models_glb(project_id: str, key: str, part: str, bridge: Bridge = _bridge) -> Response:
    if part not in _PARTS:
        raise NotFound("no such model view")
    data = bridge.model_glb(project_id, key, cast(Part, part))
    return Response(data, media_type="model/gltf-binary")
