"""Chat page: a streamed answer, and a second writer sees the chat read-only."""

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


class _Router:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tier = "local"
        self.model = "fake"

    def stream(self, system: str, user: str, tier: str) -> Iterator[str]:
        assert system
        assert user
        yield self.text


@pytest.fixture(autouse=True)
def _shield_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "STORE_DIR", tmp_path / "shield")
    load_categories(reload=True)


def test_answer_streams_over_sse(tmp_path: Path, project_dir: Path) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    bridge.use_model(_Router("A short answer."))
    info = bridge.chat_start(project, "What is EI30?", "user:ada")
    app = create_app(bridge=bridge, token="test-token", actor="user:ada")
    app.state.chat_router = _Router("A short answer.")
    client = TestClient(app, headers={TOKEN_HEADER: "test-token", "accept": "text/html"})
    url = f"/p/{project}/chats/{info.id}"
    page = client.get(url)
    assert page.status_code == 200
    assert "What is EI30?" in page.text
    started = client.post(url, data={"text": "And the width?"})
    match = re.search(r'sse-connect="([^"]+)"', started.text)
    assert match is not None
    stream = client.get(match.group(1))
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "A short answer." in stream.text
    assert "A short answer." in (project_dir / info.path).read_text(encoding="utf-8")


def test_second_writer_gets_read_only(tmp_path: Path, project_dir: Path) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    info = bridge.chat_start(project, "What is EI30?", "user:ada")
    before = (project_dir / info.path).read_bytes()
    app = create_app(bridge=bridge, token="test-token", actor="user:bob")
    client = TestClient(app, headers={TOKEN_HEADER: "test-token", "accept": "text/html"})
    page = client.get(f"/p/{project}/chats/{info.id}")
    assert page.status_code == 200
    assert "Read-only" in page.text
    assert "chat-form" not in page.text
    assert (project_dir / info.path).read_bytes() == before
