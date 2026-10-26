"""Typing where to go on the line opens it, through the local model."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from iterthink import config
from iterthink.services.bridge_real import RealBridge
from iterthink.web.app import TOKEN_HEADER, create_app

TOKEN = "test-token"


class _Router:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tier = "local"
        self.model = "fake"

    def complete(self, system: str, user: str, tier: str) -> str:
        return self.text


@pytest.fixture
def documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "Documents" / "iterthink"
    root.mkdir(parents=True)
    monkeypatch.setattr(config, "DOCUMENTS", root)
    return root


def _client(bridge: RealBridge) -> TestClient:
    app = create_app(bridge=bridge, token=TOKEN, actor="user:ada")
    return TestClient(app, headers={TOKEN_HEADER: TOKEN, "accept": "text/html"})


def test_start_screen_line_opens_the_project_the_model_names(
    tmp_path: Path, documents: Path, project_dir: Path
) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    bridge.use_intent_model(_Router("open project: P-101 Schulhaus"))
    response = _client(bridge).post("/line", data={"q": "the school one"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/p/{project}"


def test_start_screen_line_opens_the_folder_the_model_names(
    tmp_path: Path, documents: Path
) -> None:
    (documents / "Wettbewerb Halle").mkdir()
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    bridge.use_intent_model(_Router("open folder: Wettbewerb Halle"))
    response = _client(bridge).post("/line", data={"q": "the competition"})
    assert response.status_code == 200
    assert "Wettbewerb Halle" in response.text


def test_project_line_switches_to_the_project_the_model_names(
    tmp_path: Path, documents: Path, project_dir: Path, second_project_dir: Path
) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    other = bridge.make_project(second_project_dir).id
    bridge.use_intent_model(_Router("open project: P-102 Turnhalle"))
    response = _client(bridge).post(
        f"/p/{project}/line", data={"q": "switch to the gym"}, headers={"HX-Request": "true"}
    )
    assert response.headers["HX-Redirect"] == f"/p/{other}"
