"""Acceptance tests for the hash-chained event log (slice A2)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from iterthink.services.event_log import (
    LogCorrupt,
    append,
    checkpoint,
    read,
    read_all,
    read_blob,
    store_blob,
)

CONTRACT = "1.0.8"
ZEROS = "0" * 64


def _now_at(*stamps: str) -> Callable[[], datetime]:
    pending = list(stamps)

    def now() -> datetime:
        raw = pending.pop(0)
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)

    return now


def _append(
    project_dir: Path,
    machine: str,
    now: Callable[[], datetime],
    payload: dict[str, Any] | None = None,
    type: str = "note",
) -> Any:
    return append(
        project_dir,
        machine=machine,
        actor="user:simon",
        type=type,
        project="p-19c2",
        payload={"text": "hello"} if payload is None else payload,
        contract=CONTRACT,
        now=now,
    )


def _log(project_dir: Path, machine: str) -> Path:
    return project_dir / ".iterthink" / "log" / f"{machine}.jsonl"


def test_append_writes_one_canonical_line(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    event = _append(
        project, "m-7f3a", _now_at("2026-10-23T05:38:12Z"), {"ok": True, "n": 2, "text": "EI30"}
    )
    text = _log(project, "m-7f3a").read_text(encoding="utf-8")
    assert text.endswith("\n")
    lines = text.splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert lines[0] == json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    body = {key: value for key, value in parsed.items() if key != "hash"}
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert parsed["hash"] == digest == event.hash
    assert event.ts == "2026-10-23T05:38:12Z"
    assert event.seq == 1


def test_seq_increments_per_machine_log(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    clock = _now_at(
        "2026-10-23T05:00:01Z",
        "2026-10-23T05:00:02Z",
        "2026-10-23T05:00:03Z",
        "2026-10-23T05:00:04Z",
    )
    first_a = _append(project, "m-a", clock)
    first_b = _append(project, "m-b", clock)
    second_a = _append(project, "m-a", clock)
    second_b = _append(project, "m-b", clock)
    assert (first_a.seq, second_a.seq) == (1, 2)
    assert (first_b.seq, second_b.seq) == (1, 2)


def test_prev_hash_links_to_previous_line(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    clock = _now_at("2026-10-23T05:00:01Z", "2026-10-23T05:00:02Z")
    first = _append(project, "m-a", clock)
    second = _append(project, "m-a", clock)
    assert second.prev_hash == first.hash


def test_first_prev_hash_is_zeros(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    event = _append(project, "m-a", _now_at("2026-10-23T05:00:01Z"))
    assert event.prev_hash == ZEROS


def test_store_blob_is_content_addressed(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    text = "Tür EI30"
    first = store_blob(project, text)
    second = store_blob(project, text)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert first == second == f"blob:{digest}"
    assert read_blob(project, first) == text
    blob = project / ".iterthink" / "blobs" / digest
    assert blob.read_bytes() == text.encode("utf-8")
    other = store_blob(project, "other")
    assert other != first


def test_only_own_machine_log_is_written(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    clock = _now_at("2026-10-23T05:00:01Z", "2026-10-23T05:00:02Z", "2026-10-23T05:00:03Z")
    _append(project, "m-a", clock)
    other = _log(project, "m-b")
    assert not other.exists()
    _append(project, "m-b", clock)
    before = other.read_bytes()
    _append(project, "m-a", clock)
    assert other.read_bytes() == before


def test_read_all_merges_machines_in_order(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    _append(project, "m-a", _now_at("2026-10-23T05:00:02Z"), {"text": "a1"})
    _append(project, "m-a", _now_at("2026-10-23T05:00:00Z"), {"text": "a2"})
    _append(project, "m-b", _now_at("2026-10-23T05:00:02Z"), {"text": "b1"})
    merged = read_all(project)
    assert [(event.machine, event.seq, event.payload["text"]) for event in merged] == [
        ("m-a", 2, "a2"),
        ("m-a", 1, "a1"),
        ("m-b", 1, "b1"),
    ]


def test_float_in_payload_raises(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    with pytest.raises(ValueError, match="float"):
        _append(project, "m-a", _now_at("2026-10-23T05:00:01Z"), {"ratio": 1.5})
    assert not _log(project, "m-a").exists()
    with pytest.raises(ValueError, match="float"):
        _append(project, "m-a", _now_at("2026-10-23T05:00:02Z"), {"nested": {"ratio": 0.1}})
    assert not (project / ".iterthink" / "log").exists() or not _log(project, "m-a").exists()


def test_append_after_incomplete_last_line_raises(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    _append(project, "m-a", _now_at("2026-10-23T05:00:01Z"))
    log = _log(project, "m-a")
    broken = log.read_bytes()[:-1]
    log.write_bytes(broken)
    with pytest.raises(LogCorrupt):
        _append(project, "m-a", _now_at("2026-10-23T05:00:02Z"))
    assert log.read_bytes() == broken


def test_checkpoint_every_100_events_records_other_heads(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    stamps = [f"2026-10-23T05:00:{index:02d}Z" for index in range(60)]
    stamps += [f"2026-10-23T05:01:{index:02d}Z" for index in range(60)]
    clock = _now_at(*stamps)
    other = _append(project, "m-b", clock, {"text": "other"})
    for index in range(100):
        _append(project, "m-a", clock, {"n": index})
    events = list(read(_log(project, "m-a")))
    checkpoints = [event for event in events if event.type == "checkpoint"]
    assert len(events) == 101
    assert len(checkpoints) == 1
    assert checkpoints[0].seq == 101
    heads = checkpoints[0].payload["heads"]
    assert "m-a" not in heads
    assert heads["m-b"] == {"hash": other.hash, "seq": other.seq}
    assert _log(project, "m-b").read_bytes().count(b"\n") == 1


def test_source_files_untouched(
    project_dir: Path, source_snapshot: Callable[[Path], dict[str, str]]
) -> None:
    before = source_snapshot(project_dir)
    _append(project_dir, "m-a", _now_at("2026-10-23T05:00:01Z"))
    store_blob(project_dir, "note")
    checkpoint(
        project_dir,
        machine="m-a",
        actor="user:simon",
        project="p-19c2",
        contract=CONTRACT,
        now=_now_at("2026-10-23T05:00:02Z"),
    )
    assert source_snapshot(project_dir) == before
