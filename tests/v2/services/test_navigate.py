"""The model opens a file, project or folder it was offered, and nothing else."""

from __future__ import annotations

from pathlib import Path

import pytest

from iterthink import config
from iterthink.services.bridge_real import RealBridge
from iterthink.services.navigate import Place, chosen


class _Router:
    def __init__(self, text: str, tier: str = "local") -> None:
        self.text = text
        self.tier = tier
        self.model = "fake"
        self.systems: list[str] = []

    def complete(self, system: str, user: str, tier: str) -> str:
        self.systems.append(system)
        assert user
        return self.text


def _bridge(tmp_path: Path) -> RealBridge:
    return RealBridge(state_dir=tmp_path / "state", machine="m-test")


@pytest.fixture
def documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "Documents" / "iterthink"
    root.mkdir(parents=True)
    monkeypatch.setattr(config, "DOCUMENTS", root)
    return root


@pytest.mark.parametrize(
    "reply",
    [
        "open file: Pläne/Notiz.md",
        "Open file: pläne/notiz.md.",
        "`open Pläne/Notiz.md`",
        'open "file: Pläne/Notiz.md"\nBecause it matches.',
        "open file: Pläne/Notiz.md 0.9",
        "open notes: Pläne/Notiz.md",
    ],
)
def test_chosen_reads_the_open_reply(reply: str) -> None:
    places = {"file: Pläne/Notiz.md": Place("file", "Pläne/Notiz.md")}
    assert chosen(reply, places) == Place("file", "Pläne/Notiz.md")


@pytest.mark.parametrize("reply", ["chat 0.8", "open file: other.md", "none", ""])
def test_chosen_ignores_anything_else(reply: str) -> None:
    places = {"file: Pläne/Notiz.md": Place("file", "Pläne/Notiz.md")}
    assert chosen(reply, places) is None


def test_model_opens_a_file_it_was_offered(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    router = _Router("open file: Pläne/Notiz Grundriss EG.md")
    bridge.use_intent_model(router)
    found = bridge.classify_line(project, "the ground floor notes", None, "user:ada")
    assert found.via == "model"
    assert found.reopen == "Pläne/Notiz Grundriss EG.md"
    assert "file: Pläne/Notiz Grundriss EG.md" in router.systems[0]
    href = bridge.open_line(project, found, "the ground floor notes", "user:ada")
    assert href.startswith(f"/p/{project}/f/")


def test_model_switches_to_another_project(
    tmp_path: Path, project_dir: Path, second_project_dir: Path
) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    other = bridge.make_project(second_project_dir).id
    bridge.use_intent_model(_Router("open project: P-102 Turnhalle"))
    found = bridge.classify_line(project, "switch to the gym", None, "user:ada")
    assert found.goto == f"/p/{other}"
    assert bridge.open_line(project, found, "switch to the gym", "user:ada") == f"/p/{other}"


def test_model_cannot_open_a_place_it_was_not_offered(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    bridge.use_intent_model(_Router("open file: secret.md"))
    found = bridge.classify_line(project, "the secret file", None, "user:ada")
    assert found.reopen is None
    assert found.goto is None
    assert found.intent.mode == "search"


def test_start_screen_opens_a_project_by_context(
    tmp_path: Path, documents: Path, project_dir: Path, second_project_dir: Path
) -> None:
    bridge = _bridge(tmp_path)
    bridge.make_project(project_dir)
    other = bridge.make_project(second_project_dir).id
    router = _Router("open project: P-102 Turnhalle")
    bridge.use_intent_model(router)
    assert bridge.place_line("the gym") == ("project", f"/p/{other}")
    assert "project: P-101 Schulhaus" in router.systems[0]


def test_start_screen_opens_a_workspace_folder(tmp_path: Path, documents: Path) -> None:
    (documents / "Wettbewerb Halle").mkdir()
    bridge = _bridge(tmp_path)
    bridge.use_intent_model(_Router("open folder: Wettbewerb Halle"))
    place = bridge.place_line("the competition")
    assert place == ("folder", str((documents / "Wettbewerb Halle").resolve()))


def test_start_screen_without_a_model_or_a_match(tmp_path: Path, documents: Path) -> None:
    (documents / "Wettbewerb Halle").mkdir()
    bridge = _bridge(tmp_path)
    assert bridge.place_line("the competition") is None
    bridge.use_intent_model(_Router("none"))
    assert bridge.place_line("the competition") is None
    bridge.use_intent_model(_Router("open folder: Wettbewerb Halle", tier="cloud"))
    assert bridge.place_line("the competition") is None
