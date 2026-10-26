"""Review shows an image with a slider and the changed region."""

from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from iterthink.persistence.snapshots import Snapshots
from iterthink.services.bridge_real import RealBridge
from iterthink.services.projects import tracked_files
from iterthink.web.app import TOKEN_HEADER, create_app

TOKEN = "test-token"


def _png(size: tuple[int, int], box: tuple[int, int, int, int] | None) -> bytes:
    image = Image.new("RGB", size, "white")
    if box is not None:
        ImageDraw.Draw(image).rectangle(box, fill="black")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_review_uses_image_partial(tmp_path: Path, project_dir: Path) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    photo = project_dir / "photo.png"
    photo.write_bytes(_png((10, 10), None))
    snaps = Snapshots(project_dir)
    first = snaps.snapshot(tracked_files(project_dir), "before", "user:ada")
    assert first is not None
    photo.write_bytes(_png((10, 10), (8, 8, 9, 9)))
    second = snaps.snapshot(tracked_files(project_dir), "after", "user:ada")
    assert second is not None
    app = create_app(bridge=bridge, token=TOKEN, actor="user:ada")
    client = TestClient(app, headers={TOKEN_HEADER: TOKEN, "accept": "text/html"})
    page = client.get(f"/p/{project}/diff?path=photo.png&base={first.id}&target={second.id}")
    assert page.status_code == 200
    assert "<image-compare" in page.text
    assert "1 area changed" in page.text
    assert "image-box" in page.text
    assert "/static/js/image-compare.js" in page.text
