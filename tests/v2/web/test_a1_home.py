"""Home, open folder, and the project overview."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_home_shows_line_and_open_folder(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert 'placeholder="What do you want to achieve?"' in page.text
    assert 'class="dot"' in page.text
    assert 'class="menu"' in page.text
    assert 'action="/open"' in page.text or 'hx-post="/open"' in page.text
    assert 'name="path"' in page.text


def test_home_shows_no_projects(client: TestClient, project_id: str) -> None:
    page = client.get("/")
    assert "Opened projects" not in page.text
    assert "P-101 Schulhaus" not in page.text
    assert f"/p/{project_id}" not in page.text


def test_theme_is_light(client: TestClient) -> None:
    page = client.get("/")
    assert "--bg: #FFFFFF;" in page.text


def test_home_line_open_project_lists_projects(client: TestClient, project_id: str) -> None:
    page = client.post("/line", data={"q": "open project"})
    assert page.status_code == 200
    assert "P-101 Schulhaus" in page.text
    assert f'href="/p/{project_id}"' in page.text


def test_home_line_project_name_redirects(client: TestClient, project_id: str) -> None:
    page = client.post("/line", data={"q": "p-101 schulhaus"}, follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"] == f"/p/{project_id}"


def test_home_line_project_name_redirects_htmx(client: TestClient, project_id: str) -> None:
    page = client.post("/line", data={"q": "P-101 Schulhaus"}, headers={"HX-Request": "true"})
    assert page.status_code == 200
    assert page.headers["HX-Redirect"] == f"/p/{project_id}"


def test_home_line_path_lists_folders(client: TestClient, project_dir: Path) -> None:
    page = client.post("/line", data={"q": str(project_dir.parent)})
    assert page.status_code == 200
    assert project_dir.name in page.text
    assert "Make project" in page.text


def test_home_line_missing_folder_says_so(client: TestClient, tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    page = client.post("/line", data={"q": str(missing)}, headers={"HX-Request": "true"})
    assert page.status_code == 404
    assert f"no folder at {missing}" in page.text


def test_home_shows_error_responses_in_place(client: TestClient) -> None:
    page = client.get("/")
    assert '<meta name="htmx-config"' in page.text
    assert '{"code":"[45]..","swap":true,"error":true}' in page.text


def test_home_line_empty_folder_offers_make_project(client: TestClient, tmp_path: Path) -> None:
    empty = tmp_path / "test"
    empty.mkdir()
    page = client.post("/line", data={"q": str(empty)})
    assert page.status_code == 200
    assert "Make project" in page.text
    assert f'value="{empty}"' in page.text


def test_home_line_folder_with_subfolders_offers_itself_too(
    client: TestClient, project_dir: Path
) -> None:
    page = client.post("/line", data={"q": str(project_dir)})
    assert f'value="{project_dir}"' in page.text
    assert project_dir.name in page.text


def test_home_line_project_folder_links_without_make_project(
    client: TestClient, project_dir: Path, project_id: str
) -> None:
    page = client.post("/line", data={"q": str(project_dir)})
    assert f'href="/p/{project_id}"' in page.text
    assert "Make project" not in page.text


def test_home_line_unknown_shows_hint(client: TestClient) -> None:
    page = client.post("/line", data={"q": "fire protection concept"})
    assert page.status_code == 200
    assert "open project" in page.text


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
    assert 'placeholder="What do you want to achieve?"' in page.text
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
