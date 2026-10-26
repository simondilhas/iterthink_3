"""Rules, the model, and the audit line for intent."""

from __future__ import annotations

from pathlib import Path

import pytest

from iterthink.services.bridge_real import RealBridge
from iterthink.services.intent import PROMPT_ID


class _Router:
    def __init__(self, text: str, tier: str = "local") -> None:
        self.text = text
        self.tier = tier
        self.model = "fake"
        self.calls: list[str] = []

    def complete(self, system: str, user: str, tier: str) -> str:
        self.calls.append(tier)
        assert system
        assert user
        return self.text


def _bridge(tmp_path: Path) -> RealBridge:
    return RealBridge(state_dir=tmp_path / "state", machine="m-test")


def _events(project: Path) -> str:
    folder = project / ".iterthink" / "log"
    return "\n".join(path.read_text(encoding="utf-8") for path in folder.glob("*.jsonl"))


@pytest.mark.parametrize(
    ("line", "mode", "review"),
    [
        ("new document Fire concept", "document", False),
        ("neues Dokument Brandschutz", "document", False),
        ("Which doors are EI30?", "chat", False),
        ("Welche Türen sind EI30?", "chat", False),
        ("Door schedule from the model", "app", False),
        ("Liste der Türen", "app", False),
        ("find the EI30 doors", "search", False),
        ("where is the escape route", "search", False),
        ("which document mentions EI30", "search", False),
        ("compare Pflichtenheft.md and Türliste.csv", "review", True),
        ("vergleiche Pflichtenheft.md und Türliste.csv", "review", True),
    ],
)
def test_rule_based_modes(
    tmp_path: Path, project_dir: Path, line: str, mode: str, review: bool
) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    router = _Router("task 0.9")
    bridge.use_intent_model(router)
    found = bridge.classify_line(project, line, None, "user:ada")
    assert found.intent.mode == mode
    assert found.review is review
    assert found.via == "rule"
    assert router.calls == []


def test_model_fallback_respects_egress_none(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    bridge.set_egress(project, "none", "user:ada")
    router = _Router("chat 0.9", tier="cloud")
    bridge.use_intent_model(router)
    found = bridge.classify_line(project, "Fire protection concept for the hall", None, "user:ada")
    assert router.calls == []
    assert found.intent.mode == "search"


def test_intent_is_logged_with_prompt_id(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    bridge.classify_line(project, "new document Fire concept", None, "user:ada")
    text = _events(project_dir)
    assert '"type":"intent"' in text
    assert PROMPT_ID in text
    assert "blob:" in text


def test_continue_and_file_name_reopen_work(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    named = bridge.classify_line(project, "Pflichtenheft.md", None, "user:ada")
    assert named.reopen == "Pflichtenheft.md"
    href = bridge.open_line(project, named, "Pflichtenheft.md", "user:ada")
    assert f"/p/{project}/f/Pflichtenheft.md" in href
    continued = bridge.classify_line(project, "continue", None, "user:ada")
    assert continued.reopen
    assert continued.reopen.endswith(".md")
    assert bridge.interpret(project, "find the EI30 doors").mode == "search"


def test_model_answers_when_no_rule_matches(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    router = _Router("chat 0.4", tier="local")
    bridge.use_intent_model(router)
    found = bridge.classify_line(project, "Fire protection concept for the hall", None, "user:ada")
    assert router.calls == ["local"]
    assert found.via == "model"
    assert found.intent.mode == "chat"
    assert found.confidence == 0.4
    vague = _Router("not a mode")
    bridge.use_intent_model(vague)
    fallback = bridge.classify_line(
        project, "Fire protection concept for the hall", None, "user:ada"
    )
    assert vague.calls == ["local"]
    assert fallback.intent.mode == "search"
    assert bridge.start_work("find the door", "user:ada") is None
    untitled = bridge.classify_line(project, "new document", None, "user:ada")
    assert untitled.intent.mode == "document"
    assert untitled.intent.title == "Untitled"


def test_names_apps_and_blank_lines(tmp_path: Path, project_dir: Path) -> None:
    (project_dir / "extra").mkdir()
    (project_dir / "extra" / "Note.md").write_text("a\n", encoding="utf-8")
    (project_dir / "other").mkdir()
    (project_dir / "other" / "Note.md").write_text("b\n", encoding="utf-8")
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    stem = bridge.classify_line(project, "Notiz Grundriss EG.md", None, "user:ada")
    assert stem.reopen == "Pläne/Notiz Grundriss EG.md"
    ambiguous = bridge.classify_line(project, "Note.md", None, "user:ada")
    assert ambiguous.reopen is None
    blank = bridge.classify_line(project, "   ", None, "user:ada")
    assert blank.intent.mode == "search"
    app = bridge.classify_line(project, "Door schedule from the model", None, "user:ada")
    assert "soon=1" in bridge.open_line(project, app, app.intent.title, "user:ada")
    found = bridge.classify_line(project, "find the hall", None, "user:ada")
    assert "/search" in bridge.open_line(project, found, "find the hall", "user:ada")
    empty = tmp_path / "empty-project"
    empty.mkdir()
    continued = bridge.classify_line(bridge.make_project(empty).id, "continue", None, "user:ada")
    assert continued.reopen is None
