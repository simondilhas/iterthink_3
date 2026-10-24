"""Document page: full-width editor, streamed discuss, inline accept."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from iterthink import config
from iterthink.privacy_shield_settings import load_categories
from iterthink.services.bridge_real import RealBridge
from iterthink.web.app import TOKEN_HEADER, create_app

_DOC = "Pflichtenheft.md"


class _Router:
    def __init__(self, text: str, tier: str = "local") -> None:
        self.text = text
        self.tier = tier
        self.model = "fake"
        self.calls: list[str] = []

    def stream(self, system: str, user: str, tier: str) -> Iterator[str]:
        self.calls.append(tier)
        assert system
        assert user
        yield self.text


@pytest.fixture(autouse=True)
def _shield_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "STORE_DIR", tmp_path / "shield")
    load_categories(reload=True)


def _client(
    tmp_path: Path, project_dir: Path, router: _Router
) -> tuple[TestClient, RealBridge, str]:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    app = create_app(bridge=bridge, token="test-token", actor="user:ada")
    app.state.doc_router = router
    client = TestClient(app, headers={TOKEN_HEADER: "test-token", "accept": "text/html"})
    return client, bridge, project


def _stream(client: TestClient, page: str) -> str:
    match = re.search(r'sse-connect="([^"]+)"', page)
    assert match is not None
    response = client.get(match.group(1))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return response.text


def test_discuss_streams_over_sse_and_changes_nothing(tmp_path: Path, project_dir: Path) -> None:
    text = (project_dir / _DOC).read_text(encoding="utf-8")
    router = _Router("A short summary.")
    client, bridge, project = _client(tmp_path, project_dir, router)
    url = f"/p/{project}/doc/{_DOC}"
    page = client.get(url)
    assert page.status_code == 200
    assert "<md-editor" in page.text
    assert "<md-preview" in page.text
    assert "create_summary" in page.text
    assert "Discuss" in page.text
    assert "Edit" in page.text
    before = (project_dir / _DOC).read_bytes()
    started = client.post(
        url,
        data={
            "op": "margin",
            "action_id": "create_summary",
            "offset": str(text.index("Die Türen")),
            "draft": text,
        },
    )
    assert started.status_code == 200
    assert "hx-ext" in started.text
    assert "A short summary." in _stream(client, started.text)
    assert (project_dir / _DOC).read_bytes() == before
    assert bridge.proposals(project) == []
    script = client.get("/static/js/md-editor.js")
    assert script.status_code == 200
    assert "it-recall" in script.text
    assert "Mod" in script.text or "isMod" in script.text


def test_accept_inline_updates_editor_and_history(tmp_path: Path, project_dir: Path) -> None:
    text = (project_dir / _DOC).read_text(encoding="utf-8")
    client, bridge, project = _client(tmp_path, project_dir, _Router("SUGGESTED"))
    url = f"/p/{project}/doc/{_DOC}"
    started = client.post(
        url,
        data={
            "op": "margin",
            "action_id": "grammar",
            "paragraph": "1",
            "instruction": "fix it",
            "draft": text,
        },
    )
    assert "SUGGESTED" in _stream(client, started.text)
    assert "SUGGESTED" not in (project_dir / _DOC).read_text(encoding="utf-8")
    opened = client.get(url)
    assert "Accept" in opened.text
    assert 'name="proposal"' in opened.text
    match = re.search(r'name="proposal" value="([^"]+)"', opened.text)
    assert match is not None
    before = len(bridge.history(project, _DOC))
    accepted = client.post(url, data={"op": "accept", "proposal": match.group(1)})
    assert accepted.status_code == 200
    assert "SUGGESTED" in accepted.text
    assert "<textarea" in accepted.text
    saved = (project_dir / _DOC).read_text(encoding="utf-8")
    assert "SUGGESTED" in saved
    assert "EI30" not in saved
    assert len(bridge.history(project, _DOC)) == before + 1
