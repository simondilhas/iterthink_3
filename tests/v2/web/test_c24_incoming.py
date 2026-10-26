"""The import page and a dropped file that opens the diff."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from iterthink.services.bridge_real import RealBridge
from iterthink.web.app import TOKEN_HEADER, create_app

TOKEN = "incoming-token"


def _client(tmp_path: Path, project_dir: Path) -> tuple[TestClient, str]:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-web")
    project = bridge.make_project(project_dir).id
    bridge.save(project, "Notiz.md", "alt\n", "user:simon", "first")
    app = create_app(bridge=bridge, token=TOKEN, actor="user:simon")
    client = TestClient(app, headers={TOKEN_HEADER: TOKEN, "accept": "text/html"})
    return client, project


def test_incoming_page_names_the_file(tmp_path: Path, project_dir: Path) -> None:
    client, project = _client(tmp_path, project_dir)
    page = client.get(f"/p/{project}/incoming")
    assert page.status_code == 200
    assert "Work on this" in page.text
    assert "it-drop.js" in page.text


def test_dropped_existing_name_redirects_to_the_diff(tmp_path: Path, project_dir: Path) -> None:
    client, project = _client(tmp_path, project_dir)
    response = client.post(
        f"/p/{project}/incoming/drop",
        files={"file": ("Notiz.md", b"neu\n", "text/markdown")},
    )
    assert response.status_code == 200
    assert "/diff" in str(response.url)
    assert "neu" in response.text
    assert (project_dir / "Notiz.md").read_bytes() == b"neu\n"


def test_new_drop_asks_for_a_folder(tmp_path: Path, project_dir: Path) -> None:
    client, project = _client(tmp_path, project_dir)
    response = client.post(
        f"/p/{project}/incoming/drop",
        files={"file": ("extra.md", b"hello\n", "text/markdown")},
    )
    assert response.status_code == 200
    assert "Where should" in response.text
    assert not (project_dir / "extra.md").exists()
