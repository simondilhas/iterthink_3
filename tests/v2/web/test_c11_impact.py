"""The proposal page can ask for impact without deciding."""

from __future__ import annotations

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


def test_check_impact_streams_affected_files(tmp_path: Path, project_dir: Path) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    info = bridge.propose(
        project, {"Pflichtenheft.md": "# Pflichtenheft\n\nNeu.\n"}, "user:ada", "retitle"
    )
    bridge.use_impact_model(
        _Model(
            '{"suggestion":"check the door list","affected":["Türliste.csv"],"confidence":"0.80"}'
        )
    )
    app = create_app(bridge=bridge, token=TOKEN, actor="user:ada")
    client = TestClient(app, headers={TOKEN_HEADER: TOKEN, "accept": "text/html"})
    page = client.get(f"/p/{project}/proposals/{info.id}")
    assert "Check impact" in page.text
    assert 'hx-trigger="load"' in page.text
    started = client.post(f"/p/{project}/proposals/{info.id}/impact")
    assert "Checking impact" in started.text
    url = started.text.split('sse-connect="', 1)[1].split('"', 1)[0]
    streamed = client.get(url)
    assert "Türliste.csv" in streamed.text
    assert "Impact advice" in streamed.text
    still = next(item for item in bridge.proposals(project, status=None) if item.id == info.id)
    assert still.status == "open"
