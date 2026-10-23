"""Text engine acceptance tests (slice A4)."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from iterthink.compare.engine_text import TextEngine, paragraphs_of
from iterthink.compare.engines import diff

_GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "diffs"


def test_word_change_in_one_paragraph() -> None:
    result = diff("doors.md", b"Die Tueren sind EI30.", b"Die Tueren sind EI90.")
    assert result.summary == "1 paragraph changed"
    assert len(result.blocks) == 1
    block = result.blocks[0]
    assert block.kind == "refined"
    assert [segment.op for segment in block.segments] == ["equal", "delete", "insert"]
    assert block.segments[1].text == "EI30."
    assert block.segments[2].text == "EI90."


def test_paragraph_added_and_removed() -> None:
    before = b"Keep.\n\nGone.\n\nStay."
    after = b"Keep.\n\nStay.\n\nExtra."
    result = diff("note.md", before, after)
    assert [block.kind for block in result.blocks] == ["stable", "removed", "stable", "added"]
    assert result.blocks[1].before == "Gone."
    assert result.blocks[3].after == "Extra."


def test_moved_paragraph_is_not_add_and_remove() -> None:
    before = b"Alpha stays.\n\nBeta moves down.\n\nGamma stays."
    after = b"Alpha stays.\n\nGamma stays.\n\nBeta moves down."
    result = diff("note.md", before, after)
    kinds = {block.kind for block in result.blocks}
    assert "added" not in kinds
    assert "removed" not in kinds
    assert {block.after for block in result.blocks} >= {"Beta moves down.", "Gamma stays."}


def test_umlauts_and_crlf() -> None:
    text = "Die Tür ist breit.\n\nFluchtweg 1.2 m."
    result = diff("note.md", text.replace("\n", "\r\n").encode(), text.encode())
    assert all(block.kind == "stable" for block in result.blocks)
    assert any("Tür" in block.after for block in result.blocks)


def test_text_diff_golden() -> None:
    before = (_GOLDEN / "doors-before.md").read_bytes()
    after = (_GOLDEN / "doors-after.md").read_bytes()
    got = json.loads(json.dumps(asdict(diff("doors.md", before, after))))
    expected = json.loads((_GOLDEN / "doors.json").read_text(encoding="utf-8"))
    assert got == expected


@given(
    st.lists(
        st.lists(st.sampled_from(["alpha", "beta", "gamma", "delta"]), min_size=1, max_size=4).map(
            " ".join
        ),
        min_size=1,
        max_size=4,
        unique=True,
    )
)
@settings(max_examples=20, deadline=None)
def test_text_diff_reconstructs_after(paragraphs: list[str]) -> None:
    before = "\n\n".join(reversed(paragraphs))
    after = "\n\n".join(paragraphs)
    result = TextEngine().diff("note.md", before.encode(), after.encode())
    kept = [block.after for block in result.blocks if block.kind != "removed"]
    assert kept == paragraphs_of(after.encode())
    for block in result.blocks:
        if block.kind in {"removed", "added", "stable"} or not block.segments:
            continue
        rebuilt = " ".join(segment.text for segment in block.segments if segment.op != "delete")
        assert rebuilt == block.after
