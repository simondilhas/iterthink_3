"""Change ids on text blocks and per-change verdicts rebuilt from the log."""

from __future__ import annotations

import hashlib
from pathlib import Path

from iterthink.compare.engine_text import TextEngine
from iterthink.services.bridge_real import RealBridge

MD = "Pflichtenheft.md"
_BEFORE = b"# Titel\n\nDie T\xc3\xbcren sind EI30.\n\nFluchtwege 1.2 m.\n"
_AFTER = b"# Titel\n\nDie T\xc3\xbcren sind EI60.\n\nFluchtwege 1.5 m.\n\nNeu.\n"


def test_text_blocks_carry_stable_change_ids() -> None:
    first = TextEngine().diff(MD, _BEFORE, _AFTER)
    again = TextEngine().diff(MD, _BEFORE, _AFTER)
    assert [block.id for block in first.blocks] == [block.id for block in again.blocks]
    for block in first.blocks:
        if block.kind == "stable":
            assert block.id == ""
            continue
        raw = f"{MD}\0{block.before}\0{block.after}".encode()
        assert block.id == hashlib.sha256(raw).hexdigest()[:12]
    changed = [block.id for block in first.blocks if block.kind != "stable"]
    assert len(changed) == 3
    assert len(set(changed)) == 3


def _bridge(tmp_path: Path, name: str) -> RealBridge:
    return RealBridge(state_dir=tmp_path / name, machine="m-test")


def test_change_verdicts_rebuild_from_the_log(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path, "state")
    project = bridge.make_project(project_dir).id
    text = (project_dir / MD).read_text("utf-8").replace("EI30", "EI60").replace("1.2", "1.5")
    pid = bridge.propose(project, {MD: text}, "agent:checker", "Türen und Fluchtwege").id
    (diff,) = bridge.proposal_diff(project, pid)
    door, exits = [block.id for block in diff.blocks if block.kind != "stable"]
    bridge.decide_change(project, pid, door, "accepted", "user:ada")
    edited = bridge.edit_change(project, pid, exits, "Fluchtwege 1.4 m.", "user:ada")
    fresh = _bridge(tmp_path, "other-machine-state")
    assert fresh.make_project(project_dir).id == project
    (again,) = [item for item in fresh.proposals(project) if item.id == pid]
    assert again.candidate == edited.candidate
    assert dict(again.changes) == dict(edited.changes)
    assert again.changes[door] == "accepted"
    summaries = [entry.summary for entry in fresh.log(project)[:2]]
    assert any("edited" in line and pid in line for line in summaries)
