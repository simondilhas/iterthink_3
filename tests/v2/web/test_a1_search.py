"""Keyword search under the line."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_search_returns_hits_with_links_to_line(client: TestClient, project_id: str) -> None:
    page = client.get(f"/p/{project_id}/search", params={"q": "EI30"})
    assert page.status_code == 200
    assert "Pflichtenheft.md" in page.text
    assert " · " in page.text
    assert "line=" in page.text
    assert "EI30" in page.text
    assert page.text.count("<li") <= 20


def test_line_enter_opens_top_hit(client: TestClient, project_id: str) -> None:
    page = client.post(f"/p/{project_id}/line", data={"q": "EI30"}, follow_redirects=False)
    assert page.status_code == 303
    location = page.headers["location"]
    assert "Pflichtenheft.md" in location
    assert "line=" in location


def test_line_enter_without_hits_toasts(client: TestClient, project_id: str) -> None:
    page = client.post(f"/p/{project_id}/line", data={"q": "no-such-phrase"})
    assert page.status_code == 200
    assert "Nothing found" in page.text
