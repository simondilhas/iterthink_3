"""The settings page shows where each value comes from."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from iterthink.services.bridge_real import RealBridge
from iterthink.web.app import TOKEN_HEADER, create_app


def test_settings_page_shows_source_and_saves(tmp_path: Path, project_dir: Path) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    app = create_app(bridge=bridge, token="test-token", actor="user:ada")
    client = TestClient(app, headers={TOKEN_HEADER: "test-token", "accept": "text/html"})
    page = client.get(f"/p/{project}/settings")
    assert page.status_code == 200
    assert "dictation.language" in page.text
    assert "default" in page.text
    assert "Privacy shield" in page.text
    saved = client.post(
        f"/p/{project}/settings",
        data={"key": "dictation.language", "value": "de", "level": "project"},
    )
    assert saved.status_code == 200
    assert "Saved." in saved.text
    shown = {item.key: item for item in bridge.settings(project)}
    assert shown["dictation.language"].value == "de"
    assert shown["dictation.language"].source == "project"
