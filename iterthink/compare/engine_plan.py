"""Plan PDF text diff. Bounding boxes are normalised to 0–1. No model calls."""

from __future__ import annotations

import io
from typing import Any

import pdfplumber

from iterthink.services.bridge import FileDiff, FileKind

_IOU_MIN = 0.25
Line = tuple[int, str, tuple[float, float, float, float]]


class PlanEngine:
    """Compare text lines on each page by bounding-box overlap."""

    kinds: tuple[FileKind, ...] = ("plan",)

    def diff(self, path: str, before: bytes | None, after: bytes | None) -> FileDiff:
        try:
            old = _lines(before)
            new = _lines(after)
        except (OSError, ValueError, TypeError, KeyError):
            return FileDiff(path, "plan", "file changed")
        changes = _changes(old, new)
        pages = sorted({_page(change) for change in changes})
        summary = _summary(len(changes))
        return FileDiff(path, "plan", summary, details={"pages": pages, "changes": changes})


def _lines(data: bytes | None) -> list[Line]:
    if not data:
        return []
    found: list[Line] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            width = float(page.width or 1.0)
            height = float(page.height or 1.0)
            words = [dict(word) for word in (page.extract_words() or [])]
            number = page.page_number if isinstance(page.page_number, int) else 1
            found.extend(_page_lines(number, words, width, height))
    return found


def _num(word: dict[str, Any], key: str) -> float:
    return float(word[key])


def _page_lines(
    page_number: int, words: list[dict[str, Any]], width: float, height: float
) -> list[Line]:
    groups: list[list[dict[str, Any]]] = []
    for word in words:
        top = _num(word, "top")
        host = next((group for group in groups if abs(_num(group[0], "top") - top) <= 2), None)
        if host is None:
            groups.append([word])
        else:
            host.append(word)
    lines: list[Line] = []
    for group in groups:
        group.sort(key=lambda item: _num(item, "x0"))
        text = " ".join(str(item["text"]) for item in group)
        box = (
            min(_num(item, "x0") for item in group) / width,
            min(_num(item, "top") for item in group) / height,
            max(_num(item, "x1") for item in group) / width,
            max(_num(item, "bottom") for item in group) / height,
        )
        lines.append((page_number, text, box))
    return lines


def _iou(
    left: tuple[float, float, float, float], right: tuple[float, float, float, float]
) -> float:
    ix0, iy0 = max(left[0], right[0]), max(left[1], right[1])
    ix1, iy1 = min(left[2], right[2]), min(left[3], right[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    if inter <= 0:
        return 0.0
    area_left = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    area_right = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = area_left + area_right - inter
    return inter / union if union else 0.0


def _match(old: list[Line], new: list[Line]) -> list[tuple[int, int]]:
    scored = [
        (_iou(old[i][2], new[j][2]), i, j)
        for i in range(len(old))
        for j in range(len(new))
        if old[i][0] == new[j][0] and _iou(old[i][2], new[j][2]) >= _IOU_MIN
    ]
    scored.sort(reverse=True)
    used_old: set[int] = set()
    used_new: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for _score, i, j in scored:
        if i in used_old or j in used_new:
            continue
        used_old.add(i)
        used_new.add(j)
        pairs.append((i, j))
    return pairs


def _changes(old: list[Line], new: list[Line]) -> list[dict[str, object]]:
    pairs = _match(old, new)
    matched_old = {i for i, _j in pairs}
    matched_new = {j for _i, j in pairs}
    changes: list[dict[str, object]] = []
    for i, j in pairs:
        if old[i][1] == new[j][1]:
            continue
        changes.append(_change(new[j][0], list(new[j][2]), old[i][1], new[j][1]))
    for i, line in enumerate(old):
        if i not in matched_old:
            changes.append(_change(line[0], list(line[2]), line[1], ""))
    for j, line in enumerate(new):
        if j not in matched_new:
            changes.append(_change(line[0], list(line[2]), "", line[1]))
    return changes


def _page(change: dict[str, object]) -> int:
    page = change["page"]
    return page if isinstance(page, int) else 1


def _change(page: int, bbox: list[float], before: str, after: str) -> dict[str, object]:
    return {"page": page, "bbox": bbox, "before": before, "after": after}


def _summary(count: int) -> str:
    if count == 0:
        return "no changes"
    if count == 1:
        return "1 text change"
    return f"{count} text changes"
