"""Decision log and its integrity badge."""

from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from iterthink.services.bridge_fake import FakeBridge


def test_log_shows_entries_and_intact_badge(client: TestClient, project_id: str) -> None:
    page = client.get(f"/p/{project_id}/log")
    assert page.status_code == 200
    assert "Log intact" in page.text
    assert "started tracking" in page.text
    assert "simon" not in page.text or "local" in page.text


def test_log_shows_broken_badge(client: TestClient, bridge: FakeBridge, project_id: str) -> None:
    project = bridge._projects[project_id]
    project.log[0] = replace(project.log[0], hash="0" * 64)
    page = client.get(f"/p/{project_id}/log")
    assert "hash mismatch" in page.text
    assert "Log intact" not in page.text
