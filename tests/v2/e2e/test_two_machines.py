"""Two machines, one folder. Different files both stay. The same file is a conflict."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from iterthink.persistence.snapshots import Snapshots
from iterthink.services.bridge_real import RealBridge
from iterthink.services.event_log import append
from iterthink.services.projects import settings_of, tracked_files
from iterthink.services.proposals import CONTRACT, create
from iterthink.services.sync_detect import conflict_versions, reconcile

pytestmark = pytest.mark.e2e


def _bridge(tmp_path: Path, project_dir: Path, machine: str) -> tuple[RealBridge, str]:
    bridge = RealBridge(state_dir=tmp_path / machine, machine=machine)
    return bridge, bridge.make_project(project_dir).id


def _at(hour: int) -> datetime:
    return datetime(2026, 10, 25, hour, 0, tzinfo=UTC)


def _clock(hour: int) -> Callable[[], datetime]:
    def now() -> datetime:
        return _at(hour)

    return now


def _version(root: Path, machine: str, version: str, hour: int) -> None:
    append(
        root,
        machine=machine,
        actor=f"user:{machine}",
        type="version",
        project="p-test",
        payload={"path": "note", "version": version},
        contract=CONTRACT,
        now=_clock(hour),
    )


def test_two_machines_edit_different_files_both_kept(tmp_path: Path, project_dir: Path) -> None:
    _bridge(tmp_path, project_dir, "m-a")
    snaps = Snapshots(project_dir)
    parent = snaps.head().id
    files = tracked_files(project_dir)
    left = dict(files)
    left["left.md"] = b"from A\n"
    right = dict(files)
    right["right.md"] = b"from B\n"
    first = snaps.snapshot_from(parent, left, "left", "m-a")
    second = snaps.snapshot_from(parent, right, "right", "m-b")
    _version(project_dir, "m-a", first.id, 3)
    _version(project_dir, "m-b", second.id, 1)
    assert reconcile(project_dir) == []
    assert (project_dir / "left.md").read_bytes() == b"from A\n"
    assert (project_dir / "right.md").read_bytes() == b"from B\n"
    assert snaps.head().id == first.id


def test_two_machines_edit_same_file_shows_conflict(tmp_path: Path, project_dir: Path) -> None:
    _bridge(tmp_path, project_dir, "m-a")
    snaps = Snapshots(project_dir)
    parent = snaps.head().id
    original = (project_dir / "Pflichtenheft.md").read_bytes()
    files = tracked_files(project_dir)
    left = dict(files)
    left["Pflichtenheft.md"] = b"from A\n"
    right = dict(files)
    right["Pflichtenheft.md"] = b"from B\n"
    first = snaps.snapshot_from(parent, left, "left", "m-a")
    second = snaps.snapshot_from(parent, right, "right", "m-b")
    assert "Pflichtenheft.md" in reconcile(project_dir)
    versions = conflict_versions(project_dir)["Pflichtenheft.md"]
    assert set(versions) == {first.id, second.id}
    assert (project_dir / "Pflichtenheft.md").read_bytes() == original


def test_conflicting_verdicts_from_two_machines_in_review(
    tmp_path: Path, project_dir: Path
) -> None:
    bridge, project = _bridge(tmp_path, project_dir, "m-a")
    snaps = Snapshots(project_dir)
    one = create(
        project_dir,
        snaps,
        machine="m-a",
        project=project,
        changes={"Pflichtenheft.md": "from A\n"},
        actor="user:m-a",
        reason="machine A",
        baseline=None,
        now=lambda: _at(1),
    )
    two = create(
        project_dir,
        snaps,
        machine="m-b",
        project=project,
        changes={"Pflichtenheft.md": "from B\n"},
        actor="user:m-b",
        reason="machine B",
        baseline=None,
        now=lambda: _at(2),
    )
    for made, machine, hour in ((one, "m-a", 3), (two, "m-b", 4)):
        append(
            project_dir,
            machine=machine,
            actor=f"user:{machine}",
            type="verdict",
            project=project,
            payload={"proposal": made.id, "verdict": "accepted", "reason": "blob:none"},
            contract=CONTRACT,
            now=_clock(hour),
        )
    bridge.rescan_project(project)
    found = {item.id: item.status for item in bridge.proposals(project, None)}
    assert found[one.id] == "conflict"
    assert found[two.id] == "conflict"


def test_confirmed_copy_gets_new_id(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir, "m-a")
    copied = tmp_path / "P-101 copy"
    shutil.copytree(project_dir, copied)
    info = bridge.confirm_copy(project, copied)
    assert info.id != project
    assert settings_of(copied)["id"] == info.id
    assert settings_of(project_dir)["id"] == project
    assert (copied / "Pflichtenheft.md").read_text(encoding="utf-8") == (
        project_dir / "Pflichtenheft.md"
    ).read_text(encoding="utf-8")
