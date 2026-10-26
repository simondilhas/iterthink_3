"""Deliver a Word, Excel or PDF file, and bring an edited one back."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

from iterthink.services.bridge import Bridge, FileEntry
from iterthink.web.app import actor_of, bridge_of
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)
_actor = Depends(actor_of)
_path = Form()
_format = Form()
_template = Form("")
_source = Form()
_upload = File()


@router.get("/p/{project_id}/exports", response_class=HTMLResponse, name="exports")
def exports_page(request: Request, project_id: str, bridge: Bridge = _bridge) -> HTMLResponse:
    return _page(request, project_id, bridge, "", "", "")


@router.post("/p/{project_id}/exports", response_class=HTMLResponse, name="exports_post")
def exports_post(
    request: Request,
    project_id: str,
    path: str = _path,
    format: str = _format,
    template: str = _template,
    bridge: Bridge = _bridge,
) -> HTMLResponse:
    info = bridge.export(project_id, path, format, template.strip() or None)
    return _page(request, project_id, bridge, info.path, info.source_version, "")


@router.post(
    "/p/{project_id}/exports/returned", response_class=HTMLResponse, name="exports_returned"
)
def exports_returned(
    request: Request,
    project_id: str,
    source: str = _source,
    returned: UploadFile = _upload,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> HTMLResponse:
    info = bridge.import_returned(project_id, _store(returned), source, actor)
    return _page(request, project_id, bridge, "", "", info.id)


def _page(
    request: Request,
    project_id: str,
    bridge: Bridge,
    exported: str,
    version: str,
    proposal: str,
) -> HTMLResponse:
    files = [item for item in bridge.files(project_id) if _deliverable(item)]
    return render(
        request,
        "exports/page.html",
        project_id=project_id,
        files=files,
        exported=exported,
        version=version,
        proposal=proposal,
    )


def _deliverable(item: FileEntry) -> bool:
    suffix = Path(item.path).suffix.lower()
    return item.kind in {"markdown", "text"} or suffix == ".csv"


def _store(upload: UploadFile) -> Path:
    name = Path(upload.filename or "returned.bin").name
    folder = Path(tempfile.mkdtemp(prefix="iterthink-returned-"))
    dest = folder / name
    dest.write_bytes(upload.file.read())
    return dest
