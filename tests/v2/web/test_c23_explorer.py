"""Explorer panel and the start-screen rule for a new project."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from iterthink import config
from iterthink.services.bridge_real import RealBridge
from iterthink.web.app import TOKEN_HEADER, create_app

TOKEN = "test-token"


@pytest.fixture
def documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "Documents" / "iterthink"
    monkeypatch.setattr(config, "DOCUMENTS", root)
    return root


def _client(bridge: RealBridge) -> TestClient:
    app = create_app(bridge=bridge, token=TOKEN, actor="user:ada")
    return TestClient(app, headers={TOKEN_HEADER: TOKEN, "accept": "text/html"})


def test_new_subfolder_prompts_make_project(tmp_path: Path, documents: Path) -> None:
    root = tmp_path / "jobs"
    project = root / "Alt"
    project.mkdir(parents=True)
    (project / "note.md").write_text("hi\n", encoding="utf-8")
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    info = bridge.make_project(project)
    client = _client(bridge)
    first = client.get(f"/p/{info.id}/explorer")
    assert first.status_code == 200
    assert "Make project?" not in first.text
    (root / "Neu").mkdir()
    second = client.get(f"/p/{info.id}/explorer")
    assert "Neu" in second.text
    assert "Make project?</button>" in second.text
    assert (root / "Neu").is_dir()


def test_explorer_is_closed_by_default_and_projects_on_top(
    tmp_path: Path, documents: Path, project_dir: Path, second_project_dir: Path
) -> None:
    loose = project_dir.parent / "loose.txt"
    loose.write_text("x", encoding="utf-8")
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    first = bridge.make_project(project_dir)
    second = bridge.make_project(second_project_dir)
    bridge.propose(first.id, {"Pflichtenheft.md": "Neu\n"}, "user:ada", "retitle")
    client = _client(bridge)
    page = client.get(f"/p/{first.id}")
    assert page.status_code == 200
    assert 'id="files-button"' in page.text
    assert 'hx-trigger="click"' in page.text
    assert 'hx-trigger="load"' not in page.text
    assert "it-shortcuts.js" in page.text
    assert second_project_dir.name not in page.text
    assert "Pflichtenheft.md" not in page.text
    assert "Untracked" not in page.text
    panel = client.get(f"/p/{first.id}/explorer")
    text = panel.text
    assert panel.status_code == 200
    assert text.index(second_project_dir.name) < text.index("Pflichtenheft.md")
    assert f'href="/p/{second.id}"' in text
    assert "loose.txt" in text
    assert "Untracked" in text
    assert 'class="badge"' in text
    assert loose.read_text(encoding="utf-8") == "x"
    gone = client.post(
        f"/p/{first.id}/explorer/ignore",
        data={"workspace": str(project_dir.parent.resolve()), "name": "loose.txt"},
    )
    assert gone.status_code == 200
    assert "loose.txt" not in gone.text
    assert loose.is_file()
    assert "Pflichtenheft.md" in gone.text


def test_new_project_rule_on_start_screen_creates_and_opens(
    tmp_path: Path, documents: Path
) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    client = _client(bridge)
    english = client.post("/line", data={"q": "new project Schulhaus"}, follow_redirects=False)
    assert english.status_code == 303
    assert english.headers["location"].startswith("/p/")
    assert (documents / "Schulhaus").is_dir()
    german = client.post(
        "/line", data={"q": "neues Projekt Turnhalle"}, headers={"HX-Request": "true"}
    )
    assert german.status_code == 200
    assert german.headers["HX-Redirect"].startswith("/p/")
    assert (documents / "Turnhalle").is_dir()
    created = client.post("/line", data={"q": "create a new project Aula"}, follow_redirects=False)
    assert created.status_code == 303
    assert (documents / "Aula").is_dir()
    plain = client.post("/line", data={"q": "create project West"}, follow_redirects=False)
    assert (documents / "West").is_dir()
    with_a = client.post("/line", data={"q": "create a project Ost"}, follow_redirects=False)
    assert (documents / "Ost").is_dir()
    assert plain.headers["location"].startswith("/p/")
    assert with_a.headers["location"].startswith("/p/")


def test_new_project_without_name_asks_for_one(tmp_path: Path, documents: Path) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    client = _client(bridge)
    asked = client.post("/line", data={"q": "new project"})
    assert asked.status_code == 200
    assert "Name of the new project" in asked.text
    assert not documents.exists()
    german = client.post("/line", data={"q": "neues Projekt"})
    assert "Name of the new project" in german.text
    blank = client.post("/line", data={"q": "create a new project"})
    assert "Name of the new project" in blank.text
    made = client.post("/line", data={"q": "Bibliothek", "create": "1"}, follow_redirects=False)
    assert made.status_code == 303
    assert (documents / "Bibliothek").is_dir()
    assert made.headers["location"].startswith("/p/")
    opened = client.get(made.headers["location"])
    assert opened.status_code == 200
