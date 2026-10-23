"""One writer at a time for a chat, task or app file."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from iterthink.services.bridge_real import RealBridge
from iterthink.services.claims import (
    STALE_AFTER,
    Claim,
    Claimed,
    acquire,
    holder,
    release,
    take_over,
)
from iterthink.services.event_log import read_all

_CHAT = ".iterthink/chats/note.md"
_TASK = ".iterthink/tasks/door.md"
_APP = ".iterthink/apps/list.md"
_START = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)


def _at(moment: datetime) -> Callable[[], datetime]:
    def now() -> datetime:
        return moment

    return now


def _project(tmp_path: Path) -> Path:
    folder = tmp_path / "P-101"
    folder.mkdir()
    (folder / ".iterthink" / "settings").mkdir(parents=True)
    (folder / ".iterthink" / "settings" / "project.yaml").write_text(
        "egress: shielded\nid: p-claims\n", encoding="utf-8"
    )
    return folder


def test_second_acquire_raises_claimed_with_holder(tmp_path: Path) -> None:
    project = _project(tmp_path)
    first = acquire(project, _CHAT, machine="m-a", user="ada", now=_at(_START))
    with pytest.raises(Claimed) as caught:
        acquire(project, _CHAT, machine="m-b", user="bea", now=_at(_START))
    assert caught.value.holder == first
    assert holder(project, _CHAT, now=_at(_START)) == first


def test_release_frees_and_only_own_claim_is_released(tmp_path: Path) -> None:
    project = _project(tmp_path)
    claim = acquire(project, _CHAT, machine="m-a", user="ada", now=_at(_START))
    foreign = Claim(_CHAT, "m-b", "bea", claim.since, claim.heartbeat)
    release(project, foreign)
    assert holder(project, _CHAT, now=_at(_START)) == claim
    other_since = Claim(_CHAT, "m-a", "ada", "1999-01-01T00:00:00.000000Z", claim.heartbeat)
    release(project, other_since)
    assert holder(project, _CHAT, now=_at(_START)) == claim
    release(project, claim)
    assert holder(project, _CHAT, now=_at(_START)) is None
    again = acquire(project, _CHAT, machine="m-b", user="bea", now=_at(_START))
    assert again.machine == "m-b"


def test_stale_claim_is_free_for_holder_check(tmp_path: Path) -> None:
    project = _project(tmp_path)
    acquire(project, _TASK, machine="m-a", user="ada", now=_at(_START))
    later = _START + STALE_AFTER
    assert holder(project, _TASK, now=_at(later)) is None
    with pytest.raises(Claimed):
        acquire(project, _TASK, machine="m-b", user="bea", now=_at(later))


def test_take_over_logs_event_with_old_holder(tmp_path: Path) -> None:
    project = _project(tmp_path)
    acquire(project, _APP, machine="m-a", user="ada", now=_at(_START))
    later = _START + STALE_AFTER + timedelta(seconds=1)
    with pytest.raises(Claimed):
        take_over(project, _APP, machine="m-b", user="bea", actor="user:bea", now=_at(_START))
    taken = take_over(project, _APP, machine="m-b", user="bea", actor="user:bea", now=_at(later))
    assert taken.machine == "m-b"
    assert taken.user == "bea"
    assert holder(project, _APP, now=_at(later)) == taken
    events = [item for item in read_all(project) if item.type == "claim_takeover"]
    assert len(events) == 1
    event = events[0]
    assert event.actor == "user:bea"
    assert event.machine == "m-b"
    assert event.project == "p-claims"
    assert event.payload["machine"] == "m-a"
    assert event.payload["user"] == "ada"


def test_claims_only_for_chat_task_app_files(tmp_path: Path) -> None:
    project = _project(tmp_path)
    for path in (
        "Pflichtenheft.md",
        ".iterthink/log/m-a.jsonl",
        ".iterthink/chats",
        ".iterthink/chats/../settings/project.yaml",
        "/tmp/note.md",
    ):
        with pytest.raises(ValueError, match="claim"):
            acquire(project, path, machine="m-a", user="ada", now=_at(_START))
    for path in (_CHAT, _TASK, _APP):
        claim = acquire(project, path, machine="m-a", user="ada", now=_at(_START))
        release(project, claim)


def test_two_bridges_one_folder_one_writer(tmp_path: Path, project_dir: Path) -> None:
    first = RealBridge(state_dir=tmp_path / "one", machine="m-one")
    second = RealBridge(state_dir=tmp_path / "two", machine="m-two")
    info = first.make_project(project_dir)
    assert second.make_project(project_dir).id == info.id
    claim = acquire(project_dir, _CHAT, machine=first.machine, user="ada", now=_at(_START))
    with pytest.raises(Claimed) as caught:
        acquire(project_dir, _CHAT, machine=second.machine, user="bea", now=_at(_START))
    assert caught.value.holder.machine == "m-one"
    assert holder(project_dir, _CHAT, now=_at(_START)) == claim
