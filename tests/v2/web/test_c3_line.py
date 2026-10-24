"""Enter opens a surface, and typing stays a keyword search."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from iterthink import config
from iterthink.services.bridge_real import RealBridge
from iterthink.services.intent import PROMPT
from iterthink.web.app import TOKEN_HEADER, create_app

TOKEN = "test-token"


class _Router:
    def __init__(self, text: str, tier: str = "local") -> None:
        self.text = text
        self.tier = tier
        self.model = "fake"
        self.calls: list[str] = []

    def complete(self, system: str, user: str, tier: str) -> str:
        self.calls.append(tier)
        assert PROMPT.startswith("Classify")
        assert system
        return self.text


@pytest.fixture
def documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "Documents" / "iterthink"
    monkeypatch.setattr(config, "DOCUMENTS", root)
    return root


def _client(bridge: RealBridge) -> TestClient:
    app = create_app(bridge=bridge, token=TOKEN, actor="user:ada")
    return TestClient(app, headers={TOKEN_HEADER: TOKEN, "accept": "text/html"})


def test_typing_never_calls_the_model(tmp_path: Path, project_dir: Path) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    router = _Router("chat 0.9")
    bridge.use_intent_model(router)
    client = _client(bridge)
    page = client.get(f"/p/{project}/search", params={"q": "EI30"})
    assert page.status_code == 200
    assert "Pflichtenheft.md" in page.text
    assert router.calls == []


def test_enter_opens_surface_with_quiet_switch_line(tmp_path: Path, project_dir: Path) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    client = _client(bridge)
    page = client.post(
        f"/p/{project}/line",
        data={"q": "new document Fire concept"},
        headers={"HX-Request": "true"},
    )
    assert "Opened as document" in page.text
    assert "switch" in page.text
    href = page.headers["hx-redirect"]
    opened = client.get(href)
    assert opened.status_code == 200
    assert "Opened as document" in opened.text
    assert "switch" in opened.text
    text = (project_dir / "Fire concept.md").read_text(encoding="utf-8")
    assert text.strip() == "# Fire concept"


def test_switch_reopens_line_in_other_mode_and_logs_correction(
    tmp_path: Path, project_dir: Path
) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    client = _client(bridge)
    client.post(f"/p/{project}/line", data={"q": "new document Fire concept"})
    switched = client.post(
        f"/p/{project}/line",
        data={"q": "new document Fire concept", "mode": "chat"},
        headers={"HX-Request": "true"},
    )
    assert "Opened as chat" in switched.text
    assert "/chats/" in switched.headers["hx-redirect"]
    folder = project_dir / ".iterthink" / "log"
    log = "\n".join(path.read_text(encoding="utf-8") for path in folder.glob("*.jsonl"))
    assert '"correction":"chat"' in log


def test_mod_enter_is_same_as_enter_in_line(tmp_path: Path, project_dir: Path) -> None:
    script = Path("iterthink/web/static/js/the-line.js").read_text(encoding="utf-8")
    assert "requestSubmit" in script
    assert "shiftKey" in script
    assert "it-recall" in script
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    client = _client(bridge)
    page = client.get(f"/p/{project}")
    assert "the-line.js" in page.text
    entered = client.post(f"/p/{project}/line", data={"q": "find EI30"}, follow_redirects=False)
    assert "Opened as search" in entered.text


def test_review_intent_routes_to_version_diff(tmp_path: Path, project_dir: Path) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    client = _client(bridge)
    page = client.post(
        f"/p/{project}/line",
        data={"q": "compare Pflichtenheft.md and Türliste.csv"},
        follow_redirects=False,
    )
    assert page.status_code == 303
    assert "/diff" in page.headers["location"]
    assert "Pflichtenheft.md" in page.headers["location"]


def test_low_confidence_model_says_not_sure(tmp_path: Path, project_dir: Path) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    router = _Router("chat 0.4")
    bridge.use_intent_model(router)
    client = _client(bridge)
    page = client.post(
        f"/p/{project}/line",
        data={"q": "Fire protection concept for the hall"},
        headers={"HX-Request": "true"},
    )
    assert router.calls == ["local"]
    assert "Opened as chat" in page.text
    assert "not sure" in page.text
    assert "/chats/" in page.headers["hx-redirect"]


def test_unbuilt_mode_falls_back_to_search(tmp_path: Path, project_dir: Path) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    client = _client(bridge)
    page = client.post(f"/p/{project}/line", data={"q": "Door schedule from the model"})
    assert page.status_code == 200
    assert "coming soon" in page.text
    assert "Pflichtenheft.md" in page.text or "Opened as search" in page.text


def test_dot_pulses_when_proposals_are_open(tmp_path: Path, project_dir: Path) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    client = _client(bridge)
    idle = client.get(f"/p/{project}")
    assert "pulsing" not in idle.text
    bridge.propose(project, {"Pflichtenheft.md": "Neu\n"}, "user:ada", "retitle")
    waiting = client.get(f"/p/{project}")
    assert 'class="dot pulsing"' in waiting.text
    assert "tab=proposals" in waiting.text
    assert 'hx-trigger="click"' in waiting.text


def test_work_without_project_creates_one_in_default_workspace(
    tmp_path: Path, documents: Path
) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    client = _client(bridge)
    page = client.post("/line", data={"q": "new document Schulhaus plan"}, follow_redirects=False)
    assert page.status_code == 303
    assert (documents / "Schulhaus plan").is_dir()
    opened = client.get(page.headers["location"])
    assert "New project in" in opened.text
    assert "Opened as document" in opened.text
    assert (documents / "Schulhaus plan" / "Schulhaus plan.md").is_file()
