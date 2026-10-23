"""File panel, reading, and saving."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

from iterthink.services.bridge_fake import FakeBridge


def test_explorer_lists_files_with_kinds_and_proposal_badge(
    client: TestClient, bridge: FakeBridge, project_id: str
) -> None:
    bridge.propose(project_id, {"Pflichtenheft.md": "Neu\n"}, "user:simon", "retitle")
    page = client.get(f"/p/{project_id}/explorer")
    assert page.status_code == 200
    assert "Pflichtenheft.md" in page.text
    assert "markdown" in page.text
    assert "Türliste.csv" in page.text
    assert "table" in page.text
    assert "<details" in page.text
    assert "Pläne" in page.text
    assert 'class="badge"' in page.text


def test_markdown_is_rendered_and_editable(client: TestClient, project_id: str) -> None:
    page = client.get(f"/p/{project_id}/f/Pflichtenheft.md")
    assert page.status_code == 200
    assert "<h1>Pflichtenheft</h1>" in page.text
    assert "Edit" in page.text
    editing = client.get(f"/p/{project_id}/f/Pflichtenheft.md?edit=1")
    assert "<textarea" in editing.text
    assert "Die Türen im EG sind EI30." in editing.text


def test_save_writes_file_returns_toast_and_trigger(
    client: TestClient, project_id: str, project_dir: Path
) -> None:
    text = "# Pflichtenheft\n\nNeu.\n"
    page = client.post(f"/p/{project_id}/f/Pflichtenheft.md", data={"text": text})
    assert page.status_code == 200
    assert "Saved" in page.text
    assert "<textarea" in page.text
    assert "Neu." in page.text
    assert (project_dir / "Pflichtenheft.md").read_text(encoding="utf-8") == text
    trigger = page.headers["hx-trigger"]
    assert "versions-changed" in trigger
    assert "Pflichtenheft.md" in trigger


def test_save_without_changes_says_no_changes(
    client: TestClient, project_id: str, project_dir: Path
) -> None:
    original = (project_dir / "Pflichtenheft.md").read_text(encoding="utf-8")
    page = client.post(f"/p/{project_id}/f/Pflichtenheft.md", data={"text": original})
    assert page.status_code == 200
    assert "No changes" in page.text
    assert (project_dir / "Pflichtenheft.md").read_text(encoding="utf-8") == original


def test_csv_renders_as_table_with_umlaut_headers(
    client: TestClient, project_id: str, project_dir: Path
) -> None:
    (project_dir / "Türen.csv").write_text("Tür,Typ\nT01,Holz\n", encoding="utf-8")
    page = client.get(f"/p/{project_id}/f/{quote('Türen.csv')}")
    assert page.status_code == 200
    assert "<table" in page.text
    assert "Tür" in page.text
    assert "Edit as text" in page.text


def test_file_url_with_spaces_and_umlauts(client: TestClient, project_id: str) -> None:
    path = quote("Pläne/Notiz Grundriss EG.md", safe="/")
    page = client.get(f"/p/{project_id}/f/{path}")
    assert page.status_code == 200
    assert "Stand 1" in page.text


def test_path_outside_project_is_403(client: TestClient, project_id: str) -> None:
    path = quote("foo/../../etc/passwd", safe="")
    page = client.get(f"/p/{project_id}/f/{path}")
    assert page.status_code == 403
