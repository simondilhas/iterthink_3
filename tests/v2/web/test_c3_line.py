"""Enter opens a surface, and the dot shows idle, typing, working, verdict, or error."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from iterthink import config
from iterthink.services.bridge_real import RealBridge
from iterthink.services.event_log import append, checkpoint
from iterthink.services.intent import PROMPT
from iterthink.services.proposals import CONTRACT
from iterthink.web.app import TOKEN_HEADER, create_app

TOKEN = "test-token"
CSS = Path("iterthink/web/static/css/c3-line.css")
SCRIPT = Path("iterthink/web/static/js/the-line.js")


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


def _bridge(tmp_path: Path, project_dir: Path) -> tuple[RealBridge, str]:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    return bridge, bridge.make_project(project_dir).id


def _rule(css: str, selector: str) -> str:
    start = css.index(selector + " {")
    return css[start : css.index("}", start)]


@pytest.fixture
def client_home(tmp_path: Path) -> TestClient:
    return _client(RealBridge(state_dir=tmp_path / "state", machine="m-test"))


def _break_log(project_dir: Path, project: str) -> None:
    append(
        project_dir,
        machine="m-other",
        actor="user:other",
        type="settings",
        project=project,
        payload={"egress": "shielded"},
        contract=CONTRACT,
    )
    checkpoint(
        project_dir, machine="m-test", actor="user:local", project=project, contract=CONTRACT
    )
    (project_dir / ".iterthink" / "log" / "m-other.jsonl").unlink()
    append(
        project_dir,
        machine="m-other",
        actor="user:other",
        type="settings",
        project=project,
        payload={"egress": "none"},
        contract=CONTRACT,
    )


def test_typing_never_calls_the_model(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    router = _Router("chat 0.9")
    bridge.use_intent_model(router)
    page = _client(bridge).get(f"/p/{project}/search", params={"q": "EI30"})
    assert page.status_code == 200
    assert "Pflichtenheft.md" in page.text
    assert router.calls == []


def test_enter_opens_surface_with_quiet_switch_line(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
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
    bridge, project = _bridge(tmp_path, project_dir)
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
    script = SCRIPT.read_text(encoding="utf-8")
    assert "requestSubmit" in script
    assert "shiftKey" in script
    assert "it-recall" in script
    bridge, project = _bridge(tmp_path, project_dir)
    client = _client(bridge)
    page = client.get(f"/p/{project}")
    assert "the-line.js" in page.text
    entered = client.post(f"/p/{project}/line", data={"q": "find EI30"}, follow_redirects=False)
    assert "Opened as search" in entered.text


def test_review_intent_routes_to_version_diff(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    page = _client(bridge).post(
        f"/p/{project}/line",
        data={"q": "compare Pflichtenheft.md and Türliste.csv"},
        follow_redirects=False,
    )
    assert page.status_code == 303
    assert "/diff" in page.headers["location"]
    assert "Pflichtenheft.md" in page.headers["location"]


def test_low_confidence_model_says_not_sure(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    router = _Router("chat 0.4")
    bridge.use_intent_model(router)
    page = _client(bridge).post(
        f"/p/{project}/line",
        data={"q": "Fire protection concept for the hall"},
        headers={"HX-Request": "true"},
    )
    assert router.calls == ["local"]
    assert "Opened as chat" in page.text
    assert "not sure" in page.text
    assert "/chats/" in page.headers["hx-redirect"]


def test_app_without_a_builder_says_why_and_falls_back_to_search(
    tmp_path: Path, project_dir: Path
) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    page = _client(bridge).post(f"/p/{project}/line", data={"q": "Door schedule from the model"})
    assert page.status_code == 200
    assert "Could not open as app: no builder model" in page.text
    assert "coming soon" not in page.text
    assert bridge.apps(project) == []


def test_dot_is_solid_orange_when_a_verdict_waits(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    client = _client(bridge)
    idle = client.get(f"/p/{project}")
    assert 'data-state="idle"' in idle.text
    bridge.propose(project, {"Pflichtenheft.md": "Neu\n"}, "user:ada", "retitle")
    waiting = client.get(f"/p/{project}")
    assert 'data-state="verdict"' in waiting.text
    assert "tab=proposals" in waiting.text
    assert 'hx-trigger="click"' in waiting.text
    rule = _rule(CSS.read_text(encoding="utf-8"), '.dot[data-state="verdict"]')
    assert "var(--warn)" in rule
    assert "animation: none" in rule


def test_dot_idle_pulses_slowly_in_ink(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    page = _client(bridge).get(f"/p/{project}")
    assert 'data-state="idle"' in page.text
    rule = _rule(CSS.read_text(encoding="utf-8"), ".dot")
    assert "var(--fg)" in rule
    assert "it-pulse 3s" in rule


def test_dot_sits_next_to_the_line_on_the_start_screen(client_home: TestClient) -> None:
    page = client_home.get("/").text
    form = page[page.index('<form class="line-row"') : page.index("</form>")]
    assert 'id="line"' in form
    assert 'class="dot"' in form
    css = Path("iterthink/web/static/css/a1-shell.css").read_text(encoding="utf-8")
    assert "flex-direction: row" in _rule(css, ".start .line-row")


def test_dot_typing_marks_the_line() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert 'setState("typing")' in script
    assert "dataset.state = name" in script
    assert 'event.target.id !== "line"' in script
    assert "animation: none" in _rule(css, '.dot[data-state="typing"]')
    assert "dataset.base" in script


def test_dot_working_pulses_faster_until_the_answer() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert 'setState("working")' in script
    assert "htmx:afterRequest" in script
    assert "it-pulse 0.9s" in _rule(css, '.dot[data-state="working"]')


def test_dot_verdict_uses_the_warning_colour(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    bridge.propose(project, {"Pflichtenheft.md": "Neu\n"}, "user:ada", "retitle")
    page = _client(bridge).get(f"/p/{project}")
    theme = yaml.safe_load(Path("iterthink/defaults/config.yaml").read_text(encoding="utf-8"))
    css = CSS.read_text(encoding="utf-8")
    assert 'data-state="verdict"' in page.text
    assert all("warning" in theme["theme"][name] for name in ("dark", "light"))
    assert "--warn:" in page.text
    assert "var(--warn)" in css


def test_dot_error_uses_the_error_colour(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    _break_log(project_dir, project)
    page = _client(bridge).get(f"/p/{project}")
    theme = yaml.safe_load(Path("iterthink/defaults/config.yaml").read_text(encoding="utf-8"))
    css = CSS.read_text(encoding="utf-8")
    assert 'data-state="error"' in page.text
    assert all("error" in theme["theme"][name] for name in ("dark", "light"))
    assert "--error:" in page.text
    assert "var(--error)" in css


def test_dot_precedence_and_reduced_motion(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    bridge.propose(project, {"Pflichtenheft.md": "Neu\n"}, "user:ada", "retitle")
    _break_log(project_dir, project)
    page = _client(bridge).get(f"/p/{project}")
    css = CSS.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    assert 'data-state="error"' in page.text
    assert 'data-state="verdict"' not in page.text
    assert "prefers-reduced-motion: reduce" in css
    assert 'dataset.state === "error"' in script
    assert 'dataset.state === "verdict"' in script


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


def test_search_on_the_start_screen_stays_a_hint(tmp_path: Path, documents: Path) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    page = _client(bridge).post("/line", data={"q": "find the door"})
    assert page.status_code == 200
    assert "open project" in page.text
    assert not documents.exists()
