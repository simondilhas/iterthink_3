"""History panel, version diffs, and restore."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from iterthink.services.bridge_fake import FakeBridge

_SPACE = re.compile(r"\s+")


def _squash(html: str) -> str:
    return _SPACE.sub(" ", html).strip()


def _save(client: TestClient, project_id: str, path: str, text: str) -> None:
    response = client.post(f"/p/{project_id}/f/{path}", data={"text": text})
    assert response.status_code == 200


def test_panel_has_three_tabs_and_open_count(
    client: TestClient, bridge: FakeBridge, project_id: str
) -> None:
    bridge.propose(project_id, {"Pflichtenheft.md": "Neu\n"}, "user:simon", "retitle")
    page = client.get(f"/p/{project_id}/panel")
    assert page.status_code == 200
    assert "History" in page.text
    assert "Proposals (1)" in page.text
    assert "Log" in page.text
    assert "versions-changed from:body" in page.text
    assert "proposals-changed from:body" in page.text


def test_panel_is_not_loaded_on_page_load(client: TestClient, project_id: str) -> None:
    page = client.get(f"/p/{project_id}")
    assert "Proposals (" not in page.text
    assert 'hx-trigger="load"' not in page.text
    assert 'hx-trigger="click"' in page.text
    assert f"/p/{project_id}/panel" in page.text


def test_history_lists_versions_newest_first_for_path(
    client: TestClient, bridge: FakeBridge, project_id: str, project_dir: Path
) -> None:
    original = (project_dir / "Pflichtenheft.md").read_text(encoding="utf-8")
    _save(client, project_id, "Pflichtenheft.md", original.replace("EI30", "EI60"))
    _save(client, project_id, "Pflichtenheft.md", original.replace("EI30", "EI90"))
    page = client.get(
        f"/p/{project_id}/panel", params={"path": "Pflichtenheft.md", "tab": "history"}
    )
    versions = bridge.history(project_id, "Pflichtenheft.md")
    assert page.text.index(versions[0].id) < page.text.index(versions[1].id)


def test_version_page_shows_text_diff_with_ins_del(
    client: TestClient, project_id: str, project_dir: Path
) -> None:
    original = (project_dir / "Pflichtenheft.md").read_text(encoding="utf-8")
    _save(client, project_id, "Pflichtenheft.md", original.replace("EI30", "EI90"))
    panel = client.get(f"/p/{project_id}/panel", params={"path": "Pflichtenheft.md"})
    version = re.search(r"/versions/([^\"?]+)", panel.text)
    assert version is not None
    page = client.get(f"/p/{project_id}/versions/{version.group(1)}?path=Pflichtenheft.md")
    assert "<del>" in page.text
    assert "<ins>" in page.text
    assert "EI90" in page.text
    assert "unchanged paragraph" in page.text
    assert 'class="change"' in page.text
    assert "simon" in page.text
    assert "Restore this version of Pflichtenheft.md?" in page.text


def test_table_diff_highlights_cells_and_rows(
    client: TestClient, project_id: str, project_dir: Path
) -> None:
    _save(
        client,
        project_id,
        "Türliste.csv",
        "id,geschoss,typ,brandschutz\nT01,EG,Holz,EI90\nT03,OG,Stahl,EI30\n",
    )
    panel = client.get(f"/p/{project_id}/panel", params={"path": "Türliste.csv"})
    version = re.search(r"/versions/([^\"?]+)", panel.text)
    assert version is not None
    page = client.get(
        f"/p/{project_id}/versions/{version.group(1)}", params={"path": "Türliste.csv"}
    )
    assert 'title="EI30"' in page.text
    assert "EI90" in page.text
    assert 'class="added"' in page.text
    assert "T03" in page.text
    assert 'class="removed"' in page.text
    assert "T02" in page.text


def test_restore_confirms_restores_and_triggers_refresh(
    client: TestClient, bridge: FakeBridge, project_id: str, project_dir: Path
) -> None:
    original = (project_dir / "Pflichtenheft.md").read_text(encoding="utf-8")
    _save(client, project_id, "Pflichtenheft.md", original.replace("EI30", "EI90"))
    older = bridge.history(project_id, "Pflichtenheft.md")[-1]
    page = client.post(
        f"/p/{project_id}/restore",
        data={"path": "Pflichtenheft.md", "version": older.id},
    )
    assert "Restored" in page.text
    assert "versions-changed" in page.headers["hx-trigger"]
    assert "EI30" in (project_dir / "Pflichtenheft.md").read_text(encoding="utf-8")


def test_diff_text_fragment_golden(
    client: TestClient, bridge: FakeBridge, project_id: str, project_dir: Path
) -> None:
    original = (project_dir / "Pflichtenheft.md").read_text(encoding="utf-8")
    _save(client, project_id, "Pflichtenheft.md", original.replace("EI30", "EI90"))
    versions = bridge.history(project_id, "Pflichtenheft.md")
    newest, older = versions[0], versions[1]
    page = client.get(
        f"/p/{project_id}/diff",
        params={"path": "Pflichtenheft.md", "base": older.id, "target": newest.id},
    )
    expected = Path("tests/v2/golden/fragments/doors-text.html").read_text(encoding="utf-8")
    assert _squash(page.text) == _squash(expected)
