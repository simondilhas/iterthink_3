"""Pick a 1.x store, see the counts, and import it."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from iterthink.services.bridge import Bridge, Invalid
from iterthink.web.app import bridge_of
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)
_store = Form()
_target = Form("")
_action = Form("preview")


@router.get("/import", response_class=HTMLResponse, name="import_store")
def import_page(request: Request) -> HTMLResponse:
    return render(request, "import/page.html", rows=[], notice="")


@router.post("/import", response_class=HTMLResponse, name="import_store_post")
def import_post(
    request: Request,
    store: str = _store,
    target: str = _target,
    action: str = _action,
    bridge: Bridge = _bridge,
) -> HTMLResponse:
    preview = getattr(bridge, "import_preview", None)
    run = getattr(bridge, "import_run", None)
    if not callable(preview) or not callable(run):
        raise Invalid("import is not available")
    path = Path(store)
    if action == "run":
        chosen = Path(target) if target.strip() else None
        imported = run(path, chosen)
        notice = "Imported." if imported else "Already imported."
    else:
        notice = ""
    rows = preview(path)
    return render(request, "import/page.html", rows=rows, notice=notice, store=store, target=target)
