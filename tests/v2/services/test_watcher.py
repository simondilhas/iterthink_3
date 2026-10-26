"""Another machine's log line shows up when this machine rescans."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from iterthink.services.bridge_real import RealBridge
from iterthink.services.event_log import append
from iterthink.services.proposals import CONTRACT


def test_other_machine_events_appear_after_rescan(tmp_path: Path, project_dir: Path) -> None:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-a")
    project = bridge.make_project(project_dir).id
    bridge.rescan_project(project)
    moment = datetime(2026, 10, 25, 5, 0, tzinfo=UTC)
    append(
        project_dir,
        machine="m-b",
        actor="user:m-b",
        type="version",
        project=project,
        payload={"path": "Pflichtenheft.md", "version": "v-other"},
        contract=CONTRACT,
        now=lambda: moment,
    )
    fresh = bridge.rescan_project(project)
    assert any(item.startswith("m-b:") and item.endswith(":version") for item in fresh)
