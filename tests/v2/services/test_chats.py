"""Chats are Markdown files. They cite this project and do not edit it."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from iterthink import config
from iterthink.persistence.snapshots import Snapshots
from iterthink.privacy_shield_settings import load_categories
from iterthink.services.bridge import Forbidden
from iterthink.services.bridge_real import RealBridge

_DOC = "Pflichtenheft.md"


class _Router:
    def __init__(self, text: str = "The doors are EI30.", tier: str = "local") -> None:
        self.text = text
        self.tier = tier
        self.model = "fake"
        self.seen: list[str] = []

    def stream(self, system: str, user: str, tier: str) -> Iterator[str]:
        self.seen.append(user)
        assert system
        yield self.text


@pytest.fixture(autouse=True)
def _shield_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "STORE_DIR", tmp_path / "shield")
    load_categories(reload=True)


def _bridge(tmp_path: Path, machine: str = "m-test") -> RealBridge:
    return RealBridge(state_dir=tmp_path / "state", machine=machine)


def test_chat_file_is_plain_markdown_and_roundtrips(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    bridge.use_model(_Router())
    info = bridge.chat_start(project, "What is EI30?", "user:ada")
    list(bridge.chat_send(project, info.id, "And the width?", "user:ada"))
    text = (project_dir / info.path).read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "## user ·" in text
    assert "## assistant ·" in text
    assert "What is EI30?" in text
    messages = bridge.chat_messages(project, info.id)
    assert [item.role for item in messages] == ["user", "user", "assistant"]
    assert messages[0].text == "What is EI30?"
    assert messages[1].text == "And the width?"
    assert messages[2].text.startswith("The doors are EI30.")


def test_each_message_is_a_version(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    bridge.use_model(_Router())
    info = bridge.chat_start(project, "What is EI30?", "user:ada")
    assert len(Snapshots(project_dir).history(info.path)) == 1
    list(bridge.chat_send(project, info.id, "Again?", "user:ada"))
    messages = bridge.chat_messages(project, info.id)
    assert len(Snapshots(project_dir).history(info.path)) == len(messages)


def test_references_link_to_project_files(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    bridge.use_model(_Router("The doors are EI30."))
    info = bridge.chat_start(project, "Where is EI30?", "user:ada")
    assert _DOC in info.references
    list(bridge.chat_send(project, info.id, "Where is EI30?", "user:ada"))
    text = (project_dir / info.path).read_text(encoding="utf-8")
    assert f"[{_DOC}]({_DOC})" in text


def test_chat_cannot_change_files(
    tmp_path: Path, project_dir: Path, source_snapshot: Callable[[Path], dict[str, str]]
) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    bridge.use_model(_Router())
    info = bridge.chat_start(project, "What is EI30?", "user:ada")
    before = source_snapshot(project_dir)
    list(bridge.chat_send(project, info.id, "Again?", "user:ada"))
    assert source_snapshot(project_dir) == before


def test_turn_answer_into_proposal(
    tmp_path: Path, project_dir: Path, source_snapshot: Callable[[Path], dict[str, str]]
) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    bridge.use_model(_Router())
    info = bridge.chat_start(project, "What is EI30?", "user:ada")
    list(bridge.chat_send(project, info.id, "Write it down", "user:ada"))
    before = source_snapshot(project_dir)
    messages = bridge.chat_messages(project, info.id)
    proposal = bridge.chat_proposal(project, info.id, len(messages) - 1, "Answer.md", "user:ada")
    assert proposal.paths == ("Answer.md",)
    assert source_snapshot(project_dir) == before
    assert "The doors are EI30." in (project_dir / info.path).read_text(encoding="utf-8")
    assert not (project_dir / "Answer.md").exists()


def test_turn_chat_into_document(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    info = bridge.chat_start(project, "What is EI30?", "user:ada")
    path = bridge.chat_document(project, info.id, "Pläne", "Door note", "user:ada")
    assert path == "Pläne/Door note.md"
    document = (project_dir / path).read_text(encoding="utf-8")
    assert document.startswith("# ")
    assert "What is EI30?" in document
    assert path in (project_dir / info.path).read_text(encoding="utf-8")


def test_context_never_crosses_projects(
    tmp_path: Path, project_dir: Path, second_project_dir: Path
) -> None:
    secret = second_project_dir / "secret.md"
    secret.write_text("VAULTWORD lives in the vault\n", encoding="utf-8")
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    bridge.make_project(second_project_dir)
    router = _Router("Nothing secret.")
    bridge.use_model(router)
    info = bridge.chat_start(project, "What should we check?", "user:ada")
    list(bridge.chat_send(project, info.id, "Any other notes?", "user:ada"))
    assert router.seen
    assert all("VAULTWORD" not in text for text in router.seen)


def test_same_writer_continues_when_the_claim_is_quiet(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    bridge.use_model(_Router())
    info = bridge.chat_start(project, "What is EI30?", "user:ada")
    claim = project_dir / f"{info.path}.claim"
    raw = json.loads(claim.read_text(encoding="utf-8"))
    raw["heartbeat"] = "2020-01-01T00:00:00.000000Z"
    claim.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    list(bridge.chat_send(project, info.id, "Again?", "user:ada"))
    text = (project_dir / info.path).read_text(encoding="utf-8")
    assert "The doors are EI30." in text


def test_second_writer_service(tmp_path: Path, project_dir: Path) -> None:
    ada = _bridge(tmp_path, "m-ada")
    project = ada.make_project(project_dir).id
    info = ada.chat_start(project, "What is EI30?", "user:ada")
    before = (project_dir / info.path).read_bytes()
    bob = RealBridge(state_dir=tmp_path / "state", machine="m-bob")
    with pytest.raises(Forbidden):
        list(bob.chat_send(project, info.id, "I will edit", "user:bob"))
    assert (project_dir / info.path).read_bytes() == before
