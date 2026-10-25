"""Compare two versions of a model. The table is read-only."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from iterthink.services.bridge import Bridge, FileDiff
from iterthink.web.app import bridge_of
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)
_SORTS = ("guid", "class", "storey", "path")


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
    diff = bridge.diff(project_id, path, base or None, target or None)
    chosen = sort if sort in _SORTS else "guid"
    rows = [row for row in _all_rows(diff) if _keep(row, category, ifc_class, storey, pset)]
    rows.sort(key=lambda row: str(row.get(chosen, "")))
    table = _table(diff, rows)
    if request.headers.get("HX-Request"):
        return render(request, "models/table.html", table=table)
    return render(
        request,
        "models/page.html",
        project_id=project_id,
        path=path,
        base=base,
        target=target,
        category=category,
        ifc_class=ifc_class,
        storey=storey,
        pset=pset,
        sort=chosen,
        counts=_mapping(diff, "counts"),
        table=table,
    )
