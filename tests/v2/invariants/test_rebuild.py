"""The index is a projection: rebuild and replay land on the same digest."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from iterthink.services.event_log import append
from iterthink.services.indexer import Index

CONTRACT = "1.0.8"


def _clock(stamp: str) -> Callable[[], datetime]:
    moment = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)

    def now() -> datetime:
        return moment

    return now


def _note(project: Path, machine: str, stamp: str, text: str) -> None:
    append(
        project,
        machine=machine,
        actor="user:simon",
        type="note",
        project="p-test",
        payload={"text": text},
        contract=CONTRACT,
        now=_clock(stamp),
    )


@given(
    st.lists(
        st.tuples(st.sampled_from(["m-a", "m-b"]), st.text(alphabet="abc", max_size=8)),
        min_size=1,
        max_size=5,
    )
)
@settings(max_examples=20, deadline=None)
def test_shuffled_arrival_equals_full_rebuild(items: list[tuple[str, str]]) -> None:
    stamped = [
        (machine, f"2026-10-23T05:00:{index:02d}Z", text)
        for index, (machine, text) in enumerate(items)
    ]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        full_dir = root / "a" / "P"
        full_dir.mkdir(parents=True)
        for machine in ("m-a", "m-b"):
            for item_machine, stamp, text in stamped:
                if item_machine == machine:
                    _note(full_dir, machine, stamp, text)
        full = Index(root / "full.db", checkpoint_every=1)
        full.rebuild(full_dir)
        digest = full.state_digest()
        step_dir = root / "b" / "P"
        step_dir.mkdir(parents=True)
        step = Index(root / "step.db", checkpoint_every=1)
        replayed = False
        for machine in ("m-a", "m-b"):
            for item_machine, stamp, text in stamped:
                if item_machine != machine:
                    continue
                _note(step_dir, machine, stamp, text)
                result = step.update(step_dir)
                replayed = replayed or result.replayed_from is not None
        assert step.state_digest() == digest
        stamps_a = [stamp for machine, stamp, _ in stamped if machine == "m-a"]
        stamps_b = [stamp for machine, stamp, _ in stamped if machine == "m-b"]
        if stamps_a and stamps_b and min(stamps_b) < max(stamps_a):
            assert replayed


def test_deleting_db_and_rebuilding_gives_same_digest(tmp_path: Path) -> None:
    folder = tmp_path / "P"
    folder.mkdir()
    _note(folder, "m-a", "2026-10-23T05:00:01Z", "one")
    _note(folder, "m-b", "2026-10-23T05:00:02Z", "two")
    path = tmp_path / "index.db"
    index = Index(path)
    index.rebuild(folder)
    digest = index.state_digest()
    index.close()
    path.unlink()
    again = Index(path)
    again.rebuild(folder)
    assert again.state_digest() == digest
