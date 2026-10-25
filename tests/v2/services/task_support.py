"""Shared setup for the task tests."""

from __future__ import annotations

from pathlib import Path

import yaml

from iterthink.persistence.snapshots import Snapshots
from iterthink.services.bridge_real import RealBridge
from iterthink.services.task_store import path_of


def bridge_for(tmp_path: Path, project_dir: Path) -> tuple[RealBridge, str]:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    return bridge, bridge.make_project(project_dir).id


def task_text(project_dir: Path, task_id: str) -> str:
    return (project_dir / path_of(task_id)).read_text(encoding="utf-8")


def task_meta(project_dir: Path, task_id: str) -> dict[str, object]:
    text = task_text(project_dir, task_id)
    end = text.find("\n---\n", 4)
    loaded = yaml.safe_load(text[4:end])
    return loaded if isinstance(loaded, dict) else {}


def version_statuses(project_dir: Path, task_id: str) -> list[str]:
    """Spec status of the task file in each version, oldest first."""
    rel = path_of(task_id)
    snaps = Snapshots(project_dir)
    found: list[str] = []
    for version in reversed(snaps.history(rel)):
        data = snaps.file_at(version.id, rel)
        if data is None:
            continue
        text = data.decode("utf-8")
        end = text.find("\n---\n", 4)
        meta = yaml.safe_load(text[4:end])
        if isinstance(meta, dict) and isinstance(meta.get("status"), str):
            found.append(str(meta["status"]))
    return found
