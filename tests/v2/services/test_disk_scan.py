"""Files changed outside iterthink become versions."""

from __future__ import annotations

import os
from pathlib import Path

from iterthink.persistence.snapshots import Snapshots
from iterthink.services.bridge_real import RealBridge
from iterthink.services.disk_scan import DEBOUNCE_S, Debounce, scan
from iterthink.services.event_log import read_all

MB = 1024 * 1024


def _project(tmp: Path, name: str = "P") -> tuple[RealBridge, str, Path]:
    folder = tmp / name
    folder.mkdir()
    (folder / "note.md").write_text("one\n", encoding="utf-8")
    bridge = RealBridge(state_dir=tmp / "state", machine="m-test")
    info = bridge.make_project(folder)
    return bridge, info.id, folder


def _kinds(folder: Path) -> list[object]:
    return [event.payload.get("kind") for event in read_all(folder) if event.type == "version"]


def test_external_edit_becomes_version_with_disk_change_kind(tmp_path: Path) -> None:
    bridge, project, folder = _project(tmp_path)
    (folder / "note.md").write_text("two\n", encoding="utf-8")
    result = scan(folder, Snapshots(folder), machine="m-test", project=project)
    assert result.changed == ("note.md",)
    assert result.version
    assert bridge.history(project)[0].message == "changed on disk"
    assert bridge.history(project)[0].id == result.version
    event = next(
        item
        for item in read_all(folder)
        if item.type == "version" and item.payload.get("kind") == "disk_change"
    )
    assert event.actor.startswith("user:")
    assert event.payload.get("source") == "file"
    assert event.payload.get("version") == result.version


def test_external_edit_puts_open_proposal_in_conflict(tmp_path: Path) -> None:
    bridge, project, folder = _project(tmp_path)
    made = bridge.propose(project, {"note.md": "from the agent\n"}, "agent:checker", "retitle")
    (folder / "note.md").write_text("typed outside\n", encoding="utf-8")
    scan(folder, Snapshots(folder), machine="m-test", project=project)
    assert [item.id for item in bridge.proposals(project, "conflict")] == [made.id]


def test_removed_and_added_files_recorded(tmp_path: Path) -> None:
    _bridge, project, folder = _project(tmp_path)
    (folder / "note.md").unlink()
    (folder / "extra.md").write_text("new\n", encoding="utf-8")
    result = scan(folder, Snapshots(folder), machine="m-test", project=project)
    assert result.removed == ("note.md",)
    assert result.added == ("extra.md",)
    assert "disk_remove" in _kinds(folder)
    assert "disk_change" in _kinds(folder)


def test_move_between_projects_references_source(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _left, left_id, left = _project(workspace, "A")
    right = workspace / "B"
    right.mkdir()
    (right / "other.md").write_text("other\n", encoding="utf-8")
    right_bridge = RealBridge(state_dir=workspace / "state-b", machine="m-two")
    right_id = right_bridge.make_project(right).id
    body = (left / "note.md").read_bytes()
    (left / "note.md").unlink()
    (right / "note.md").write_bytes(body)
    scan(left, Snapshots(left), machine="m-test", project=left_id)
    result = scan(right, Snapshots(right), machine="m-two", project=right_id)
    assert result.added == ("note.md",)
    payload = next(
        event.payload
        for event in read_all(right)
        if event.type == "version" and event.payload.get("kind") == "disk_change"
    )
    assert f"{left_id}/note.md" in str(payload.get("moved_from"))


def test_excluded_and_oversized_files_not_tracked(tmp_path: Path) -> None:
    bridge, project, folder = _project(tmp_path)
    (folder / "~$book.xlsx").write_text("lock", encoding="utf-8")
    (folder / "notes.tmp").write_text("tmp", encoding="utf-8")
    (folder / "keep.md").write_text("keep\n", encoding="utf-8")
    big = folder / "big.bin"
    big.write_bytes(b"")
    os.truncate(big, 200 * MB + 1)
    result = scan(folder, Snapshots(folder), machine="m-test", project=project)
    assert result.added == ("keep.md",)
    paths = bridge.history(project)[0].paths
    assert "keep.md" in paths
    assert "~$book.xlsx" not in paths
    assert "notes.tmp" not in paths
    assert "big.bin" not in paths


def test_burst_of_writes_makes_one_version(tmp_path: Path) -> None:
    _bridge, project, folder = _project(tmp_path)
    clock = {"now": 0.0}
    seen: list[str | None] = []

    def run() -> None:
        (folder / "note.md").write_text(f"edit {len(seen)}\n", encoding="utf-8")
        result = scan(folder, Snapshots(folder), machine="m-test", project=project)
        seen.append(result.version)

    waiting = Debounce(DEBOUNCE_S, run, clock=lambda: clock["now"])
    waiting.push()
    clock["now"] = 0.5
    waiting.push()
    clock["now"] = 1.0
    waiting.push()
    assert waiting.poll() is False
    clock["now"] = 1.0 + DEBOUNCE_S
    assert waiting.poll() is True
    assert waiting.poll() is False
    assert len(seen) == 1
    assert seen[0]


def test_scan_twice_without_changes_is_noop(tmp_path: Path) -> None:
    bridge, project, folder = _project(tmp_path)
    (folder / "note.md").write_text("two\n", encoding="utf-8")
    first = scan(folder, Snapshots(folder), machine="m-test", project=project)
    second = scan(folder, Snapshots(folder), machine="m-test", project=project)
    assert first.version
    assert second.version is None
    assert second.changed == ()
    assert second.added == ()
    assert second.removed == ()
    assert bridge.history(project)[0].id == first.version
