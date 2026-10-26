"""Read the other machines' logs. A rescan stands in when the share drops events."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast

from iterthink.services.bridge import Invalid, ProjectInfo
from iterthink.services.event_log import Event, read_all
from iterthink.services.projects import settings_of
from iterthink.services.sync_detect import assign_copy_id, note_verdict_conflicts, reconcile

INTERVAL_S = 60


class _Registry(Protocol):
    def place(self, project: str, folder: Path) -> str: ...


class _Host(Protocol):
    machine: str
    state_dir: Path
    _now: Callable[[], datetime]
    _registry: _Registry

    def _root(self, project: str) -> Path: ...
    def _event(
        self, root: Path, project: str, actor: str, kind: str, payload: dict[str, object]
    ) -> None: ...
    def _info(self, folder: Path) -> ProjectInfo: ...


class SharedBridge:
    """Rescan and the copy question, on the real bridge."""

    def rescan_project(self, project: str) -> list[str]:
        host = cast(_Host, self)
        root = host._root(project)
        fresh = rescan(root, host.state_dir, project)
        note_verdict_conflicts(root, host.machine, project, host._now)
        return [f"{event.machine}:{event.seq}:{event.type}" for event in fresh]

    def confirm_copy(self, project: str, folder: Path) -> ProjectInfo:
        host = cast(_Host, self)
        root = folder.resolve()
        current = settings_of(root).get("id")
        if current != project:
            raise Invalid("that folder is not this project")
        new_id = assign_copy_id(root)
        host._registry.place(new_id, root)
        host._event(
            root,
            new_id,
            "user:local",
            "project_created",
            {"copied_from": project, "name": root.name},
        )
        return host._info(root)


def rescan(root: Path, state_dir: Path, project: str) -> list[Event]:
    """Events appended since the last rescan, then catch the folder up."""
    events = read_all(root)
    previous = _load(state_dir, project)
    fresh = [event for event in events if (event.machine, event.seq) not in previous]
    _store(state_dir, project, events)
    reconcile(root)
    return fresh


def _load(state_dir: Path, project: str) -> set[tuple[str, int]]:
    path = state_dir / "sync" / f"{project}.json"
    if not path.is_file():
        return set()
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return set()
    found: set[tuple[str, int]] = set()
    for item in raw:
        if (
            isinstance(item, list)
            and len(item) == 2
            and isinstance(item[0], str)
            and isinstance(item[1], int)
        ):
            found.add((item[0], item[1]))
    return found


def _store(state_dir: Path, project: str, events: list[Event]) -> None:
    folder = state_dir / "sync"
    folder.mkdir(parents=True, exist_ok=True)
    payload = [[event.machine, event.seq] for event in events]
    path = folder / f"{project}.json"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
