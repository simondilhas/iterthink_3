"""Plan page: overlays, two views, and more than one page."""

from __future__ import annotations

import html
import io
import re
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from iterthink.persistence.snapshots import Snapshots
from iterthink.services.bridge_real import RealBridge
from iterthink.services.projects import tracked_files
from iterthink.web.app import TOKEN_HEADER, create_app

_TOKEN = "test-token"


def _pdf(pages: list[tuple[str, float]]) -> bytes:
    writer = PdfWriter()
    for text, height in pages:
        page = writer.add_blank_page(width=612, height=height)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 18 Tf 72 120 Td ({text}) Tj ET".encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _client(tmp_path: Path, project_dir: Path) -> tuple[TestClient, RealBridge, str]:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    app = create_app(bridge=bridge, token=_TOKEN, actor="user:ada")
    client = TestClient(app, headers={TOKEN_HEADER: _TOKEN, "accept": "text/html"})
    return client, bridge, project


def _style(bbox: object) -> str:
    assert isinstance(bbox, list)
    x0, y0, x1, y1 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    return (
        f"left:{x0 * 100:.4f}%;top:{y0 * 100:.4f}%;"
        f"width:{(x1 - x0) * 100:.4f}%;height:{(y1 - y0) * 100:.4f}%"
    )


def test_overlays_positioned_from_bbox(tmp_path: Path, project_dir: Path) -> None:
    (project_dir / "plan.pdf").write_bytes(_pdf([("EI30", 792)]))
    client, bridge, project = _client(tmp_path, project_dir)
    (project_dir / "plan.pdf").write_bytes(_pdf([("EI90", 792)]))
    made = Snapshots(project_dir).snapshot(tracked_files(project_dir), "updated plan", "user:ada")
    assert made is not None
    diff = bridge.diff(project, "plan.pdf")
    changes = diff.details["changes"]
    assert isinstance(changes, list)
    assert len(changes) == 1
    change = changes[0]
    assert isinstance(change, dict)
    page = client.get(f"/p/{project}/plans?path=plan.pdf")
    assert page.status_code == 200
    assert "<plan-viewer" in page.text
    assert 'class="plan-box ins"' in page.text
    assert _style(change["bbox"]) in page.text
    assert "EI90" in page.text


def test_side_by_side_and_swipe_views_render(tmp_path: Path, project_dir: Path) -> None:
    (project_dir / "plan.pdf").write_bytes(_pdf([("EI30", 792)]))
    client, _bridge, project = _client(tmp_path, project_dir)
    (project_dir / "plan.pdf").write_bytes(_pdf([("EI90", 792)]))
    Snapshots(project_dir).snapshot(tracked_files(project_dir), "updated plan", "user:ada")
    side = client.get(f"/p/{project}/plans?path=plan.pdf&view=side")
    assert side.status_code == 200
    assert 'data-view="side"' in side.text
    assert side.text.count("<plan-viewer") >= 2
    assert side.text.count("<img") >= 2
    swipe = client.get(f"/p/{project}/plans?path=plan.pdf&view=swipe")
    assert swipe.status_code == 200
    assert 'data-view="swipe"' in swipe.text
    assert 'type="range"' in swipe.text
    script = client.get("/static/js/it-plan-view.js")
    assert script.status_code == 200
    assert "plan-viewer" in script.text
    assert "zoom" in script.text


def test_multi_page_navigation(tmp_path: Path, project_dir: Path) -> None:
    (project_dir / "plan.pdf").write_bytes(_pdf([("ONE", 792), ("TWO", 400)]))
    client, _bridge, project = _client(tmp_path, project_dir)
    first = client.get(f"/p/{project}/plans?path=plan.pdf&page=1")
    assert first.status_code == 200
    assert 'aria-current="page"' in first.text
    assert "page=2" in first.text
    second = client.get(f"/p/{project}/plans?path=plan.pdf&page=2")
    assert second.status_code == 200
    assert re.search(r'aria-current="page"[^>]*>\s*2\s*<', second.text)
    images = re.findall(r'src="([^"]*plans/page[^"]*)"', second.text)
    assert images
    src = html.unescape(images[0])
    assert "page=2" in src
    png1 = client.get(src.replace("page=2", "page=1"))
    png2 = client.get(src)
    assert png1.status_code == 200
    assert png2.status_code == 200
    assert png1.headers["content-type"].startswith("image/png")
    assert png1.content != png2.content


def test_legacy_notes_are_read_only(tmp_path: Path, project_dir: Path) -> None:
    (project_dir / "plan.pdf").write_bytes(_pdf([("EI30", 792)]))
    store = project_dir / ".iterthink"
    store.mkdir(parents=True)
    conn = sqlite3.connect(store / "store.sqlite3")
    conn.execute("CREATE TABLE content (id INTEGER PRIMARY KEY, attributes TEXT)")
    conn.execute(
        "CREATE TABLE paragraph_user_comments ("
        "id INTEGER PRIMARY KEY, content_version_id INTEGER, annotation_kind TEXT, "
        "plan_page_index INTEGER, plan_norm_x REAL, plan_norm_y REAL, "
        "geometry_json TEXT, body TEXT)"
    )
    conn.execute(
        "INSERT INTO content (id, attributes) VALUES (1, ?)",
        ('{"snapshot_relpath": "plan.pdf"}',),
    )
    conn.execute(
        "INSERT INTO paragraph_user_comments VALUES (1, 1, 'pin', 0, 0.2, 0.3, NULL, ?)",
        ("check the stair",),
    )
    conn.commit()
    conn.close()
    client, _bridge, project = _client(tmp_path, project_dir)
    page = client.get(f"/p/{project}/plans?path=plan.pdf")
    assert page.status_code == 200
    match = re.search(
        r'<span class="plan-note"[^>]*>check the stair</span>',
        page.text,
    )
    assert match is not None
    assert 'data-read-only="note"' in match.group(0)
    assert "<form" not in match.group(0)
    assert "<button" not in match.group(0)
