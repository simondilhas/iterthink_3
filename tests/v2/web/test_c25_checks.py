"""The checks panel streams symbols and stays closed until asked."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from iterthink.services.bridge_real import RealBridge
from iterthink.web.app import TOKEN_HEADER, create_app

TOKEN = "test-token"


class _Model:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tier = "local"
        self.calls: list[str] = []

    def complete(self, system: str, user: str, tier: str) -> str:
        self.calls.append(tier)
        assert system
        return self.text


def test_run_streams_results_and_changes_nothing(
    tmp_path: Path,
    project_dir: Path,
    source_snapshot: Callable[[Path], dict[str, str]],
) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    bridge.use_checks_model(_Model('{"symbol":"~","finding":"doors stay EI30"}'))
    before = source_snapshot(project_dir)
    original = (project_dir / "Pflichtenheft.md").read_text(encoding="utf-8")
    app = create_app(bridge=bridge, token=TOKEN, actor="user:ada")
    client = TestClient(app, headers={TOKEN_HEADER: TOKEN, "accept": "text/html"})
    started = client.post(
        f"/p/{project}/checks",
        data={"path": "Pflichtenheft.md", "check": "project_impact"},
    )
    assert "Checking" in started.text
    url = started.text.split('sse-connect="', 1)[1].split('"', 1)[0]
    streamed = client.get(url)
    assert "~" in streamed.text
    assert "doors stay EI30" in streamed.text
    assert "check-symbols" in streamed.text
    assert source_snapshot(project_dir) == before
    assert (project_dir / "Pflichtenheft.md").read_text(encoding="utf-8") == original
    assert all(item.status == "open" for item in bridge.proposals(project, status=None))


def test_panel_closed_by_default(tmp_path: Path, project_dir: Path) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    app = create_app(bridge=bridge, token=TOKEN, actor="user:ada")
    client = TestClient(app, headers={TOKEN_HEADER: TOKEN, "accept": "text/html"})
    page = client.get(f"/p/{project}/checks?path=Pflichtenheft.md")
    assert page.status_code == 200
    assert '<details id="checks-panel">' in page.text
    assert '<details id="checks-panel" open' not in page.text
    assert "Project impact" in page.text
    assert "/static/js/check-symbols.js" in page.text
    script = client.get("/static/js/check-symbols.js")
    assert script.status_code == 200
    assert "shiftKey" in script.text
    assert '"c"' in script.text
    assert "check-symbols" in script.text
