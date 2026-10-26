"""Change ids, candidate hashes and the text rebuilt from per-change verdicts.

Pure functions shared by the text engine and both bridges.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import cast

from iterthink.services.bridge import Block, ChangeStatus, FileDiff

DECIDABLE_KINDS = frozenset({"markdown", "text"})


def change_id(path: str, before: str, after: str) -> str:
    """First 12 hex characters of sha256 over path, before and after."""
    raw = f"{path}\0{before}\0{after}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


def with_ids(path: str, blocks: tuple[Block, ...]) -> tuple[Block, ...]:
    """Every non-stable block gets its change id; stable blocks keep ``""``."""
    return tuple(
        block
        if block.kind == "stable"
        else replace(block, id=change_id(path, block.before, block.after))
        for block in blocks
    )


def candidate_of(files: Mapping[str, bytes]) -> str:
    """sha256 over the sorted (path, proposed bytes) pairs of a draft."""
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(files[path])
        digest.update(b"\0")
    return digest.hexdigest()


def change_ids(diffs: list[FileDiff]) -> list[str]:
    """Ids of the decidable changes, in document order."""
    return [block.id for diff in diffs for block in diff.blocks if block.id]


def statuses(
    diffs: list[FileDiff], verdicts: Mapping[str, str], whole: str
) -> dict[str, ChangeStatus]:
    """Change id to open, accepted or rejected. ``whole`` fills undecided ids of a
    proposal decided as a whole (``open`` while it is still open)."""
    fallback = whole if whole in ("accepted", "rejected") else "open"
    return {key: cast(ChangeStatus, verdicts.get(key, fallback)) for key in change_ids(diffs)}


def recorded(verdicts: Mapping[str, str]) -> dict[str, ChangeStatus]:
    """The verdicts given one by one, as contract change states."""
    return {key: cast(ChangeStatus, value) for key, value in verdicts.items()}


def rebuild(blocks: tuple[Block, ...], pick: Callable[[Block], str], proposed: str) -> str:
    """Paragraphs joined by a blank line; a trailing newline as in ``proposed``."""
    parts: list[str] = []
    for block in blocks:
        text = block.before if block.kind == "stable" else pick(block)
        if text:
            parts.append(text)
    joined = "\n\n".join(parts)
    return joined + "\n" if joined and proposed.endswith("\n") else joined


def decided_text(blocks: tuple[Block, ...], verdicts: Mapping[str, str], proposed: str) -> str:
    """Accepted changes take ``after``, rejected ones ``before``."""
    return rebuild(
        blocks,
        lambda block: block.after if verdicts.get(block.id) == "accepted" else block.before,
        proposed,
    )


def edited_text(blocks: tuple[Block, ...], target: str, text: str, proposed: str) -> str:
    """The draft with the change ``target`` replaced by ``text``."""
    return rebuild(blocks, lambda block: text if block.id == target else block.after, proposed)
