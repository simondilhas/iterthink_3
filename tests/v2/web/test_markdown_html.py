"""Raw HTML inside a Markdown file is shown as text, never run in the shell."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from iterthink import config
from iterthink.privacy_shield_settings import load_categories
from iterthink.services.bridge_real import RealBridge
from iterthink.web.app import TOKEN_HEADER, create_app

_DOC = "Notiz.md"
_HOSTILE = (
    "# Notiz\n\n"
    "Text <img src=x onerror=\"fetch('/p')\"> mehr.\n\n"
    "<script>fetch('/p')</script>\n\n"
    "[Link](javascript:fetch('/p'))\n"
)


class _Router:
    tier = "local"
    model = "fake"

    def stream(self, system: str, user: str, tier: str) -> Iterator[str]:
        yield ""


@pytest.fixture(autouse=True)
def _shield_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "STORE_DIR", tmp_path / "shield")
    load_categories(reload=True)


def _client(tmp_path: Path, project_dir: Path) -> tuple[TestClient, str]:
    (project_dir / _DOC).write_text(_HOSTILE, encoding="utf-8")
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    app = create_app(bridge=bridge, token="test-token", actor="user:ada")
    app.state.doc_router = _Router()
    client = TestClient(app, headers={TOKEN_HEADER: "test-token", "accept": "text/html"})
    return client, project


def _assert_inert(html: str) -> None:
    assert "<img" not in html
    assert "<script>fetch" not in html
    assert 'href="javascript:' not in html
    assert "&lt;img src=x onerror=" in html
    assert "&lt;script&gt;" in html


@pytest.mark.parametrize("edit", ["", "?edit=1"])
def test_file_view_escapes_raw_html(tmp_path: Path, project_dir: Path, edit: str) -> None:
    client, project = _client(tmp_path, project_dir)
    page = client.get(f"/p/{project}/f/{_DOC}{edit}")
    assert page.status_code == 200
    assert "<h1>Notiz</h1>" in page.text
    _assert_inert(page.text.split("<textarea", 1)[0])


def test_document_preview_escapes_raw_html(tmp_path: Path, project_dir: Path) -> None:
    client, project = _client(tmp_path, project_dir)
    page = client.get(f"/p/{project}/doc/{_DOC}")
    assert page.status_code == 200
    preview = page.text.split("<md-preview", 1)[1].split("</md-preview>", 1)[0]
    assert "<h1>Notiz</h1>" in preview
    _assert_inert(preview)
