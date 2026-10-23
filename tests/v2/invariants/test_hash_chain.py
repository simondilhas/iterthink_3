"""Property tests: the hash chain detects tampering and accepts intact logs."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from iterthink.services.event_log import append
from iterthink.services.verify_log import verify, verify_all

CONTRACT = "1.0.8"


def _clock(stamp: str) -> Callable[[], datetime]:
    moment = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)

    def now() -> datetime:
        return moment

    return now


def _append_text(project_dir: Path, machine: str, text: str, stamp: str) -> None:
    append(
        project_dir,
        machine=machine,
        actor="user:simon",
        type="note",
        project="p-19c2",
        payload={"text": text},
        contract=CONTRACT,
        now=_clock(stamp),
    )


@given(st.text(min_size=0, max_size=24), st.integers(min_value=0, max_value=10**6))
@settings(max_examples=40, deadline=None)
def test_any_single_byte_change_breaks_verification(text: str, index_seed: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "p"
        project.mkdir()
        _append_text(project, "m-a", text, "2026-10-23T05:00:01Z")
        _append_text(project, "m-a", text + "x", "2026-10-23T05:00:02Z")
        log = project / ".iterthink" / "log" / "m-a.jsonl"
        original = log.read_bytes()
        index = index_seed % len(original)
        mutated = bytearray(original)
        mutated[index] = (mutated[index] + 1) % 256
        log.write_bytes(mutated)
        result = verify(log)
        assert result.ok is False
        assert result.error_line is not None


@given(st.lists(st.text(min_size=0, max_size=20), min_size=0, max_size=6))
@settings(max_examples=25, deadline=None)
def test_untouched_log_always_verifies(texts: list[str]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "p"
        project.mkdir()
        for index, text in enumerate(texts):
            stamp = f"2026-10-23T05:00:{index:02d}Z"
            _append_text(project, "m-a", text, stamp)
            _append_text(project, "m-b", text, stamp)
        assert verify_all(project).ok is True
        log = project / ".iterthink" / "log" / "m-a.jsonl"
        if texts:
            result = verify(log)
            assert result.ok is True
            assert result.error_line is None
            assert result.lines == len(texts)
