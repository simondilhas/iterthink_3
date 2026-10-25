"""Change classes a program can see. No model call."""

from __future__ import annotations

import csv
import io
import re
from functools import lru_cache
from typing import Any

_WORD = re.compile(r"\w+", re.UNICODE)
_TYPO = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
)
CHANGE_CLASSES = ("whitespace", "spelling", "typography", "csv_format", "typos")


def classify(path: str, before: bytes, after: bytes) -> frozenset[str]:
    """Classes that fully explain the edit. ``content`` means they do not."""
    if before == after:
        return frozenset()
    if _csv_format(path, before, after):
        return frozenset({"csv_format"})
    return _text_classes(_decode(before), _decode(after))


def _text_classes(old: str, new: str) -> frozenset[str]:
    folded = _spell_fold(old, new)
    if folded is None:
        return frozenset({"content"})
    left, right = _typo(folded), _typo(new)
    if _compact(left) != _compact(right):
        return frozenset({"content"})
    classes: set[str] = set()
    if folded != old:
        classes.add("spelling")
    if left != folded or right != new:
        classes.add("typography")
    if left != right:
        classes.add("whitespace")
    return frozenset(classes) if classes else frozenset({"content"})


def _spell_fold(old: str, new: str) -> str | None:
    found = list(_WORD.finditer(old))
    targets = _WORD.findall(new)
    if len(found) != len(targets):
        return None
    parts: list[str] = []
    cursor = 0
    for match, target in zip(found, targets, strict=True):
        source = match.group()
        parts.append(old[cursor : match.start()])
        if source != target and not _spelling_fix(source, target):
            return None
        parts.append(target)
        cursor = match.end()
    parts.append(old[cursor:])
    return "".join(parts)


def _spelling_fix(source: str, target: str) -> bool:
    old, new = source.casefold(), target.casefold()
    if old == new or not _near(old, new) or _known(old):
        return False
    return any(spell.correction(old) == new for spell in _checkers())


def _known(word: str) -> bool:
    return any(word in spell for spell in _checkers())


def _near(left: str, right: str) -> bool:
    if abs(len(left) - len(right)) > 2:
        return False
    previous = list(range(len(right) + 1))
    for index, char in enumerate(left, 1):
        current = [index]
        lowest = index
        for column, other in enumerate(right, 1):
            cost = 0 if char == other else 1
            current.append(min(current[-1] + 1, previous[column] + 1, previous[column - 1] + cost))
            lowest = min(lowest, current[-1])
        if lowest > 2:
            return False
        previous = current
    return previous[-1] <= 2


def _csv_format(path: str, before: bytes, after: bytes) -> bool:
    if not path.lower().endswith((".csv", ".tsv")):
        return False
    old, new = _cells(before), _cells(after)
    return old is not None and old == new


def _cells(data: bytes) -> list[list[str]] | None:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    return [list(row) for row in csv.reader(io.StringIO(text))]


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _typo(text: str) -> str:
    return text.translate(_TYPO)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


@lru_cache(maxsize=1)
def _checkers() -> tuple[Any, ...]:
    from spellchecker import SpellChecker

    return tuple(SpellChecker(language=code, distance=2) for code in ("de", "en", "fr", "it"))
