"""Render a plan page and place change boxes on it. No model calls."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import quote

import pypdfium2 as pdfium

from iterthink.persistence.snapshots import SnapshotError, Snapshots
from iterthink.services.bridge import FileDiff, Invalid, NotFound
from iterthink.services.projects import compare_file, inside, relative, version_history

_VIEWS = ("single", "side", "swipe")
_SCALE = 150 / 72
_NOTE_KINDS = ("pin", "revision_cloud", "change_region")


class _Host(Protocol):
    state_dir: Path

    def _root(self, project: str) -> Path: ...


@dataclass(frozen=True)
class Overlay:
    kind: str
    style: str
    before: str
    after: str


@dataclass(frozen=True)
class Note:
    style: str
    text: str


@dataclass(frozen=True)
class PlanScreen:
    path: str
    page: int
    pages: tuple[int, ...]
    view: str
    summary: str
    before_url: str
    after_url: str
    overlays: tuple[Overlay, ...]
    notes: tuple[Note, ...]


def page_image(data: bytes, page: int, version: str, cache: Path) -> Path:
    """PNG at 150 dpi. A second call for the same version does not render again."""
    dest = cache / _key(version) / f"{page}.png"
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_suffix(f".{page}.tmp")
    temporary.write_bytes(_render_png(data, page))
    temporary.replace(dest)
    return dest


def _key(version: str) -> str:
    clean = "".join(ch for ch in version if ch.isalnum())
    if not clean:
        raise Invalid("unknown version")
    return clean


def _render_png(data: bytes, page: int) -> bytes:
    doc = pdfium.PdfDocument(data)
    try:
        if page < 1 or page > len(doc):
            raise NotFound(f"no page {page}")
        pdf_page = doc[page - 1]
        bitmap = pdf_page.render(scale=_SCALE)
        try:
            image = bitmap.to_pil()
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            return buf.getvalue()
        finally:
            bitmap.close()
            pdf_page.close()
    finally:
        doc.close()


def _count(data: bytes) -> int:
    doc = pdfium.PdfDocument(data)
    try:
        return len(doc)
    finally:
        doc.close()


def _style(x0: float, y0: float, x1: float, y1: float) -> str:
    width = (x1 - x0) * 100
    height = (y1 - y0) * 100
    return f"left:{x0 * 100:.4f}%;top:{y0 * 100:.4f}%;width:{width:.4f}%;height:{height:.4f}%"


def _quad(bbox: object) -> tuple[float, float, float, float] | None:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    nums: list[float] = []
    for item in bbox:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        nums.append(float(item))
    return (nums[0], nums[1], nums[2], nums[3])


def _boxes(diff: FileDiff, page: int) -> tuple[Overlay, ...]:
    raw = diff.details.get("changes", [])
    if not isinstance(raw, list):
        return ()
    found: list[Overlay] = []
    for item in raw:
        box = _one_box(item, page)
        if box is not None:
            found.append(box)
    return tuple(found)


def _one_box(item: object, page: int) -> Overlay | None:
    if not isinstance(item, dict) or item.get("page") != page:
        return None
    quad = _quad(item.get("bbox"))
    if quad is None:
        return None
    before = item.get("before")
    after = item.get("after")
    old = before if isinstance(before, str) else ""
    new = after if isinstance(after, str) else ""
    return Overlay("ins" if new else "del", _style(*quad), old, new)


def _pdf_bytes(root: Path, path: str, version: str) -> tuple[bytes, str]:
    rel = relative(path)
    if version and version != "current":
        return _at(root, rel, version), _key(version)
    full = inside(root, rel)
    if not full.is_file():
        raise NotFound(f"no file {rel}")
    data = full.read_bytes()
    return data, hashlib.sha256(data).hexdigest()


def _at(root: Path, rel: str, version: str) -> bytes:
    try:
        data = Snapshots(root).file_at(version, rel)
    except SnapshotError as exc:
        raise NotFound(f"unknown version {version}") from exc
    if data is None:
        raise NotFound(f"{rel} is not in that version")
    return data


def _saved_id(root: Path, rel: str, data: bytes) -> str:
    history = version_history(root, rel)
    if history and Snapshots(root).file_at(history[0].id, rel) == data:
        return history[0].id
    return "current"


def _before_id(root: Path, rel: str, base: str, target: str, after: bytes) -> str:
    if base:
        return base
    history = version_history(root, rel)
    ids = [item.id for item in history]
    if target and target in ids:
        index = ids.index(target) + 1
        return ids[index] if index < len(ids) else ""
    for item in history:
        stored = Snapshots(root).file_at(item.id, rel)
        if stored is not None and stored != after:
            return item.id
    return ""


def _url(project: str, path: str, version: str, page: int) -> str:
    if not version:
        return ""
    rel = quote(path, safe="")
    ver = quote(version, safe="")
    return f"/p/{project}/plans/page?path={rel}&version={ver}&page={page}"


def legacy_notes(root: Path, path: str, page: int) -> tuple[Note, ...]:
    """Pins and clouds from a 1.x store, when that file is in the project."""
    database = _store(root)
    if database is None:
        return ()
    try:
        conn = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    except sqlite3.Error:
        return ()
    try:
        return _read_notes(conn, path, page)
    except sqlite3.Error:
        return ()
    finally:
        conn.close()


def _store(root: Path) -> Path | None:
    for candidate in (root / ".iterthink" / "store.sqlite3", root / "store.sqlite3"):
        if candidate.is_file():
            return candidate
    return None


def _read_notes(conn: sqlite3.Connection, path: str, page: int) -> tuple[Note, ...]:
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = {str(row[0]) for row in tables}
    if "paragraph_user_comments" not in names or "content" not in names:
        return ()
    query = (
        "SELECT c.annotation_kind, c.plan_page_index, c.plan_norm_x, c.plan_norm_y, "
        "c.geometry_json, c.body, content.attributes "
        "FROM paragraph_user_comments AS c JOIN content ON content.id = c.content_version_id"
    )
    found: list[Note] = []
    for row in conn.execute(query):
        note = _one_note(row, path, page)
        if note is not None:
            found.append(note)
    return tuple(found)


def _one_note(row: object, path: str, page: int) -> Note | None:
    if not isinstance(row, tuple) or len(row) != 7:
        return None
    kind, index, x_pos, y_pos, geometry, body, attributes = row
    if not isinstance(kind, str) or kind not in _NOTE_KINDS or index != page - 1:
        return None
    if _relpath(attributes) != path:
        return None
    style = _note_style(kind, x_pos, y_pos, geometry)
    text = body.strip() if isinstance(body, str) else ""
    if not style or not text:
        return None
    return Note(style, text)


def _relpath(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(loaded, dict):
        return ""
    found = loaded.get("snapshot_relpath") or loaded.get("resolved_path")
    return found if isinstance(found, str) else ""


def _note_style(kind: str, x_pos: object, y_pos: object, geometry: object) -> str | None:
    if kind != "pin":
        return _cloud_style(geometry)
    if isinstance(x_pos, bool) or isinstance(y_pos, bool):
        return None
    if not isinstance(x_pos, (int, float)) or not isinstance(y_pos, (int, float)):
        return None
    return f"left:{float(x_pos) * 100:.4f}%;top:{float(y_pos) * 100:.4f}%"


def _cloud_style(geometry: object) -> str | None:
    if not isinstance(geometry, str):
        return None
    try:
        loaded = json.loads(geometry)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    quad = _quad([loaded.get(name) for name in ("x0", "y0", "x1", "y1")])
    return None if quad is None else _style(*quad)


class PlansBridge:
    """Plan pages on the real bridge. The route only draws what this returns."""

    def plan_png(self, project: str, path: str, version: str, page: int) -> bytes:
        host = cast(_Host, self)
        data, key = _pdf_bytes(host._root(project), path, version)
        image = page_image(data, page, key, host.state_dir / "plan-cache")
        return image.read_bytes()

    def plan_screen(
        self, project: str, path: str, base: str, target: str, page: int, view: str
    ) -> PlanScreen:
        host = cast(_Host, self)
        root = host._root(project)
        rel = relative(path)
        after, _key_ignored = _pdf_bytes(root, rel, target)
        after_id = target or _saved_id(root, rel, after)
        count = max(_count(after), 1)
        current = page if 1 <= page <= count else 1
        diff = compare_file(root, rel, base or None, target or None)
        before = _before_id(root, rel, base, target, after)
        return PlanScreen(
            path=rel,
            page=current,
            pages=tuple(range(1, count + 1)),
            view=view if view in _VIEWS else "single",
            summary=diff.summary,
            before_url=_url(project, rel, before, current),
            after_url=_url(project, rel, after_id, current),
            overlays=_boxes(diff, current),
            notes=legacy_notes(root, rel, current),
        )
