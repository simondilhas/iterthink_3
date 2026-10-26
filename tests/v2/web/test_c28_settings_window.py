"""The Settings page: one list of sections, saves on change, opened from the menu."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from iterthink.services.bridge_real import RealBridge
from iterthink.web.app import TOKEN_HEADER, create_app

TOKEN = "test-token"
TITLES = [
    "Models",
    "Privacy",
    "Appearance",
    "Paths",
    "Dictation",
    "Prompts and checks",
    "Search index",
    "Storage and usage",
    "Shortcuts",
]


@pytest.fixture
def bridge(tmp_path: Path) -> RealBridge:
    return RealBridge(state_dir=tmp_path / "state", machine="m-test")


@pytest.fixture
def client(bridge: RealBridge) -> TestClient:
    app = create_app(bridge=bridge, token=TOKEN, actor="user:ada")
    return TestClient(app, headers={TOKEN_HEADER: TOKEN, "accept": "text/html"})


def test_menu_links_to_settings_on_start_screen_and_in_project(
    client: TestClient, bridge: RealBridge, project_dir: Path
) -> None:
    assert 'href="/settings"' in client.get("/").text
    project = bridge.make_project(project_dir).id
    page = client.get(f"/p/{project}").text
    assert 'class="menu"' in page
    assert f'href="/p/{project}/settings"' in page


def test_all_sections_render(client: TestClient, bridge: RealBridge, project_dir: Path) -> None:
    project = bridge.make_project(project_dir).id
    page = client.get(f"/p/{project}/settings")
    assert page.status_code == 200
    positions = [page.text.index(f">{title}</h2>") for title in TITLES]
    assert positions == sorted(positions)
    for anchor in ("models", "privacy", "shortcuts"):
        assert f'href="#{anchor}"' in page.text
    start = client.get("/settings")
    assert start.status_code == 200
    assert ">Models</h2>" in start.text
    assert ">Search index</h2>" not in start.text


def test_change_posts_and_shows_saved(
    client: TestClient, bridge: RealBridge, project_dir: Path
) -> None:
    project = bridge.make_project(project_dir).id
    response = client.post(
        "/settings/set",
        data={"project": project, "key": "dictation.model", "value": "tiny", "level": "project"},
    )
    assert response.status_code == 200
    assert "Saved" in response.text
    assert "Use default" in response.text
    shown = {item.key: item for item in bridge.settings(project)}
    assert shown["dictation.model"].value == "tiny"
    cleared = client.post(
        "/settings/set",
        data={"project": project, "key": "dictation.model", "level": "project", "clear": "1"},
    )
    assert "Use default" not in cleared.text
    egress = client.post(
        "/settings/set",
        data={"project": project, "key": "egress", "value": "none", "level": "project"},
    )
    assert "Saved" in egress.text
    assert bridge.projects()[0].egress == "none"


def test_appearance_changes_root_tokens(client: TestClient, bridge: RealBridge) -> None:
    light = client.get("/").text
    assert "--bg: #FFFFFF" in light
    response = client.post(
        "/settings/set", data={"key": "appearance", "value": "dark", "level": "machine"}
    )
    assert response.headers.get("HX-Refresh") == "true"
    assert "--bg: #0F0F12" in client.get("/").text


def test_invalid_yaml_is_refused_on_the_page(
    client: TestClient, bridge: RealBridge, project_dir: Path
) -> None:
    project = bridge.make_project(project_dir).id
    response = client.post(
        "/settings/file",
        data={"project": project, "name": "rules.yaml", "level": "project", "text": "a: ["},
    )
    assert response.status_code == 200
    assert "Not valid YAML" in response.text
    assert not (project_dir / ".iterthink" / "settings" / "rules.yaml").exists()
    saved = client.post(
        "/settings/file",
        data={"project": project, "name": "rules.yaml", "level": "project", "text": "rules: []"},
    )
    assert "Saved" in saved.text


def test_index_rebuild_from_the_page(
    client: TestClient, bridge: RealBridge, project_dir: Path
) -> None:
    project = bridge.make_project(project_dir).id
    response = client.post("/settings/index", data={"project": project})
    assert response.status_code == 200
    assert "Rebuilt" in response.text


def test_ollama_status_fragment(client: TestClient, bridge: RealBridge) -> None:
    class _Client:
        def list(self) -> dict[str, object]:
            return {"models": [{"model": "qwen2.5:3b"}]}

    bridge._ollama_client = _Client()
    response = client.get("/settings/ollama")
    assert '<datalist id="ollama-models">' in response.text
    assert "qwen2.5:3b" in response.text
    assert "ollama pull" in response.text


def test_shortcuts_reach_the_page(client: TestClient, bridge: RealBridge) -> None:
    assert 'name="it-shortcuts"' in client.get("/").text
    assert "Mod+K" in client.get("/").text
