"""CSV chart and one proposed row. Screens and the tests share this."""

from __future__ import annotations

import csv
import io
import json

_WIDTH = 480
_HEIGHT = 200
_PAD = 28


def chart_svg(text: str, kind: str, x_key: str, y_key: str) -> str:
    """An SVG bar or line chart. No library."""
    points = _pairs(text, x_key, y_key)
    if kind == "line":
        return _line(points)
    return _bars(points)


def next_document(existing: str, fields: list[str], values: list[str], kind: str) -> str:
    """The file text after one row is added. The caller proposes it."""
    if kind == "json":
        rows = _loaded(existing)
        rows.append(_object(fields, values))
        return json.dumps(rows, indent=2) + "\n"
    return _csv_row(existing, fields, values)


def _pairs(text: str, x_key: str, y_key: str) -> list[tuple[str, float]]:
    found: list[tuple[str, float]] = []
    for row in csv.DictReader(io.StringIO(text)):
        label = row.get(x_key) or ""
        raw = row.get(y_key) or ""
        found.append((label, _number(raw)))
    return found


def _number(raw: str) -> float:
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _bars(points: list[tuple[str, float]]) -> str:
    peak = max((value for _label, value in points), default=0.0)
    slot = (_WIDTH - 2 * _PAD) / max(len(points), 1)
    parts = [_open()]
    for index, (label, value) in enumerate(points):
        height = 0.0 if peak <= 0 else (value / peak) * (_HEIGHT - 2 * _PAD)
        left = _PAD + index * slot + slot * 0.2
        top = _HEIGHT - _PAD - height
        parts.append(_rect(left, top, slot * 0.6, height))
        parts.append(_label(left, label))
    parts.append("</svg>")
    return "".join(parts)


def _line(points: list[tuple[str, float]]) -> str:
    peak = max((value for _label, value in points), default=0.0)
    span = max(len(points) - 1, 1)
    usable = _WIDTH - 2 * _PAD
    coords: list[str] = []
    parts = [_open()]
    for index, (label, value) in enumerate(points):
        left = _PAD + usable * index / span
        height = 0.0 if peak <= 0 else (value / peak) * (_HEIGHT - 2 * _PAD)
        top = _HEIGHT - _PAD - height
        coords.append(f"{_px(left)},{_px(top)}")
        parts.append(_label(left, label))
    points_attr = " ".join(coords)
    parts.append(f'<polyline points="{points_attr}" fill="none" stroke="currentColor"></polyline>')
    parts.append("</svg>")
    return "".join(parts)


def _open() -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_WIDTH} {_HEIGHT}">'


def _rect(left: float, top: float, width: float, height: float) -> str:
    return (
        f'<rect x="{_px(left)}" y="{_px(top)}" width="{_px(width)}" height="{_px(height)}"></rect>'
    )


def _label(left: float, text: str) -> str:
    return f'<text x="{_px(left)}" y="{_HEIGHT - 8}">{_escape(text)}</text>'


def _px(value: float) -> str:
    return str(round(value))


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _csv_row(existing: str, fields: list[str], values: list[str]) -> str:
    extra = io.StringIO()
    csv.writer(extra, lineterminator="\n").writerow(values)
    if not existing.strip():
        header = io.StringIO()
        csv.writer(header, lineterminator="\n").writerow(fields)
        return header.getvalue() + extra.getvalue()
    body = existing if existing.endswith("\n") else existing + "\n"
    return body + extra.getvalue()


def _loaded(existing: str) -> list[object]:
    if not existing.strip():
        return []
    try:
        loaded = json.loads(existing)
    except json.JSONDecodeError:
        return []
    if isinstance(loaded, dict):
        return [loaded]
    if isinstance(loaded, list):
        return list(loaded)
    return []


def _object(fields: list[str], values: list[str]) -> dict[str, str]:
    padded = list(values) + [""] * max(len(fields) - len(values), 0)
    return {field: padded[index] for index, field in enumerate(fields)}
