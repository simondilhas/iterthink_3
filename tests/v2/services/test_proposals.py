"""Proposals rebuilt from the log, and the checkpoint written on close."""

from __future__ import annotations

from pathlib import Path

from iterthink.services.bridge_real import RealBridge
from iterthink.services.event_log import read_all

MD = "Pflichtenheft.md"


def test_restart_keeps_proposals_and_statuses(tmp_path: Path, project_dir: Path) -> None:
    state = tmp_path / "state"
    bridge = RealBridge(state_dir=state, machine="m-test")
    project = bridge.make_project(project_dir).id
    text = (project_dir / MD).read_text(encoding="utf-8").replace("EI30", "EI60")
    made = bridge.propose(project, {MD: text}, "agent:checker", "Brandschutz")
    bridge.reject(project, made.id, "user:simon", "EI30 reicht")
    again = RealBridge(state_dir=state, machine="m-test")
    assert [item.id for item in again.proposals(project, "rejected")] == [made.id]
    assert again.proposals(project, "open") == []


def test_proposal_status_moves_with_the_folder(tmp_path: Path, project_dir: Path) -> None:
    state = tmp_path / "state"
    bridge = RealBridge(state_dir=state, machine="m-test")
    project = bridge.make_project(project_dir).id
    text = (project_dir / MD).read_text(encoding="utf-8").replace("EI30", "EI60")
    made = bridge.propose(project, {MD: text}, "agent:checker", "Brandschutz")
    copied = tmp_path / "elsewhere"
    import shutil

    shutil.copytree(project_dir, copied)
    fresh = RealBridge(state_dir=tmp_path / "other", machine="m-other")
    opened = fresh.make_project(copied)
    assert opened.id == project
    assert [item.id for item in fresh.proposals(project, "open")] == [made.id]


def test_every_version_has_a_log_event_with_version_id(tmp_path: Path, project_dir: Path) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    bridge.save(project, MD, "eins\n", "user:simon")
    made = bridge.propose(project, {MD: "zwei\n"}, "agent:checker", "retitle")
    bridge.accept(project, made.id, "user:simon", "passt")
    seen = {
        event.payload.get("version")
        for event in read_all(project_dir)
        if isinstance(event.payload.get("version"), str)
    }
    assert {item.id for item in bridge.history(project)} <= seen


def test_log_verifies_after_session_and_fails_after_tamper(
    tmp_path: Path, project_dir: Path
) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    bridge.save(project, MD, "eins\n", "user:simon")
    assert bridge.verify(project).ok
    log = project_dir / ".iterthink" / "log" / "m-test.jsonl"
    raw = bytearray(log.read_bytes())
    raw[raw.index(b'"actor"') + 8] ^= 1
    log.write_bytes(raw)
    assert bridge.verify(project).ok is False


def test_accepting_one_proposal_marks_competing_one_conflict(
    tmp_path: Path, project_dir: Path
) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    original = (project_dir / MD).read_text(encoding="utf-8")
    first = bridge.propose(project, {MD: original.replace("EI30", "EI60")}, "agent:a", "one")
    second = bridge.propose(project, {MD: original.replace("EI30", "EI90")}, "agent:b", "two")
    bridge.accept(project, first.id, "user:simon", "passt")
    assert [item.id for item in bridge.proposals(project, "accepted")] == [first.id]
    assert [item.id for item in bridge.proposals(project, "conflict")] == [second.id]


def test_close_writes_checkpoint(tmp_path: Path, project_dir: Path) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    bridge.close()
    assert any(event.type == "checkpoint" for event in read_all(project_dir))
    assert bridge.verify(project).ok
