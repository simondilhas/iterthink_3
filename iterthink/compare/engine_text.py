"""Paragraph diff for markdown and plain text. No embeddings and no model calls."""

from __future__ import annotations

from difflib import SequenceMatcher

from iterthink.compare.margin import split_paragraphs
from iterthink.compare.paragraph_align import DiffParagraph, compute_alignment
from iterthink.compare.paragraph_compare import _base_kind_from_diff
from iterthink.services.bridge import Block, FileDiff, FileKind, Segment

_CHANGED = frozenset({"refined", "modified", "rephrased"})


class TextEngine:
    """Align paragraphs, then word segments inside each changed paragraph."""

    kinds: tuple[FileKind, ...] = ("markdown", "text")

    def diff(self, path: str, before: bytes | None, after: bytes | None) -> FileDiff:
        old = _paragraphs(before)
        new = _paragraphs(after)
        if not old:
            blocks = tuple(Block("added", "", paragraph) for paragraph in new)
        elif not new:
            blocks = tuple(Block("removed", paragraph, "") for paragraph in old)
        else:
            rows = compute_alignment("\n\n".join(old), "\n\n".join(new))
            blocks = tuple(_block(row) for row in rows)
        return FileDiff(path, "text", _summary(blocks), blocks=blocks)


def _text(data: bytes | None) -> str:
    if not data:
        return ""
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _paragraphs(data: bytes | None) -> list[str]:
    text = _text(data)
    if not text.strip():
        return []
    return [paragraph for paragraph in split_paragraphs(text) if paragraph]


def _block(row: DiffParagraph) -> Block:
    kind = _base_kind_from_diff(row)
    before = row.old_text or ""
    after = row.new_text or ""
    segments = () if kind in {"added", "removed", "stable"} else _segments(before, after)
    return Block(kind=kind, before=before, after=after, segments=segments)


def _segments(before: str, after: str) -> tuple[Segment, ...]:
    old_words = before.split()
    new_words = after.split()
    matcher = SequenceMatcher(a=old_words, b=new_words)
    found: list[Segment] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            found.append(Segment("equal", " ".join(old_words[i1:i2])))
        elif op == "delete":
            found.append(Segment("delete", " ".join(old_words[i1:i2])))
        elif op == "insert":
            found.append(Segment("insert", " ".join(new_words[j1:j2])))
        else:
            found.append(Segment("delete", " ".join(old_words[i1:i2])))
            found.append(Segment("insert", " ".join(new_words[j1:j2])))
    return tuple(segment for segment in found if segment.text)


def _summary(blocks: tuple[Block, ...]) -> str:
    changed = sum(1 for block in blocks if block.kind in _CHANGED)
    added = sum(1 for block in blocks if block.kind == "added")
    removed = sum(1 for block in blocks if block.kind == "removed")
    parts: list[str] = []
    if changed:
        word = "paragraph" if changed == 1 else "paragraphs"
        parts.append(f"{changed} {word} changed")
    if added:
        parts.append(f"{added} added")
    if removed:
        parts.append(f"{removed} removed")
    return ", ".join(parts) if parts else "no changes"


def paragraphs_of(data: bytes | None) -> list[str]:
    """Paragraphs the text engine compares. Exposed for the reconstruction test."""
    return _paragraphs(data)
