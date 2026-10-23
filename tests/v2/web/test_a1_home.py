"""Home, open folder, and the project overview."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_home_shows_line_and_open_folder(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert 'placeholder="What do you want to do?"' in page.text
    assert 'class="dot"' in page.text
    assert 'action="/open"' in page.text or 'hx-post="/open"' in page.text
    assert 'name="path"' in page.text


def test_open_folder_lists_folders_with_make_project(client: TestClient, project_dir: Path) -> None:
    page = client.post("/open", data={"path": str(project_dir.parent)})
    assert page.status_code == 200
    assert project_dir.name in page.text
    assert "Make project" in page.text


def test_make_project_redirects_to_project(client: TestClient, project_dir: Path) -> None:
    page = client.post("/projects", data={"path": str(project_dir)}, follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"].startswith("/p/")


def test_project_page_is_line_and_overview_only(client: TestClient, project_id: str) -> None:
    page = client.get(f"/p/{project_id}")
    assert page.status_code == 200
    assert 'placeholder="What do you want to do?"' in page.text
    assert "markdown" in page.text
    assert "Pflichtenheft.md" not in page.text
    assert 'hx-trigger="load"' not in page.text
    assert "Files" in page.text
    assert "/explorer" in page.text
    assert 'hx-trigger="click"' in page.text


def test_history_button_only_if_panel_route_exists(client: TestClient, project_id: str) -> None:
    page = client.get(f"/p/{project_id}")
    assert "History" in page.text
    assert f'hx-get="/p/{project_id}/panel"' in page.text
    assert 'hx-trigger="click"' in page.text
    assert 'hx-trigger="load"' not in page.text
    assert "Proposals (" not in page.text
