"""Turn a 1.x store into snapshots and decision-log events. The store is not written."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from iterthink.persistence.snapshots import Snapshots
from iterthink.services.bridge import Bridge, Invalid
from iterthink.services.event_log import LogCorrupt, read_all
from iterthink.services.projects import tracked_files

Emit = Callable[[Path, str, str, str, dict[str, object]], None]


def preview(store: Path) -> list[dict[str, object]]:
    """Counts per 1.x project, and whether its folder is still on disk."""
    with _connect(store) as conn:
        projects = _projects(conn)
        versions = _grouped(conn, "content", "version_no > 0")
        verdicts = _grouped(
            conn, "content_changes", "intent_verdict IS NOT NULL AND intent_verdict != ''"
        )
        notes = _annotation_counts(conn)
    rows: list[dict[str, object]] = []
    for project in projects:
        pid = _ident(project["id"])
        root = str(project["root"] or "")
        rows.append(
            {
                "id": pid,
                "name": str(project["name"] or pid),
                "root": root,
                "versions": versions.get(pid, 0),
                "verdicts": verdicts.get(pid, 0),
                "annotations": notes.get(pid, 0),
                "ready": bool(root) and Path(root).is_dir(),
            }
        )
    return rows


def run_import(store: Path, bridge: Bridge, target: Path | None = None) -> list[str]:
    """Import each project once. Returns the 2.0 project ids that were new."""
    emit = _emit(bridge)
    imported: list[str] = []
    for row in preview(store):
        folder = _folder(row, target)
        info = bridge.make_project(folder)
        if _marked(folder, store):
            continue
        _import_project(store, folder, info.id, _ident(row["id"]), emit)
        imported.append(info.id)
    return imported


def main(argv: list[str] | None = None) -> int:
    """``python -m iterthink.services.importer_1x STORE [--target DIR] [--preview]``."""
    parser = argparse.ArgumentParser(description="Import a 1.x store into a 2.0 project")
    parser.add_argument("store", type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args(argv)
    if args.preview:
        for row in preview(args.store):
            print(
                f"{row['name']}: {row['versions']} versions, "
                f"{row['verdicts']} verdicts, {row['annotations']} annotations"
            )
        return 0
    from iterthink.services.bridge import get_bridge

    run_import(args.store, get_bridge(), args.target)
    return 0


def _connect(store: Path) -> sqlite3.Connection:
    database = (store / "store.sqlite3").resolve()
    if not database.is_file():
        raise Invalid("no 1.x store here")
    opened = f"file:{database.as_posix()}?mode=ro&immutable=1"
    conn = sqlite3.connect(opened, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _has(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _projects(conn: sqlite3.Connection) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    if _has(conn, "projects"):
        for row in conn.execute("SELECT id, name, root_path FROM projects ORDER BY id"):
            found.append({"id": row["id"], "name": row["name"], "root": row["root_path"]})
    if found or not _has(conn, "content"):
        return found
    for row in conn.execute("SELECT DISTINCT project_id FROM content ORDER BY project_id"):
        found.append({"id": row["project_id"], "name": str(row["project_id"]), "root": ""})
    return found


def _grouped(conn: sqlite3.Connection, table: str, where: str) -> dict[int, int]:
    if not _has(conn, table):
        return {}
    counts: dict[int, int] = {}
    query = f"SELECT project_id, count(*) AS n FROM {table} WHERE {where} GROUP BY project_id"  # noqa: S608
    for row in conn.execute(query):
        counts[int(row["project_id"])] = int(row["n"])
    return counts


def _annotation_counts(conn: sqlite3.Connection) -> dict[int, int]:
    counts: dict[int, int] = {}
    _add_notes(conn, counts, "paragraph_user_comments")
    _add_notes(conn, counts, "impact_annotations")
    return counts


def _add_notes(conn: sqlite3.Connection, counts: dict[int, int], table: str) -> None:
    if not _has(conn, table) or not _has(conn, "content"):
        return
    query = (
        f"SELECT c.project_id AS project_id, count(*) AS n FROM {table} AS a "  # noqa: S608
        "JOIN content AS c ON c.id = a.content_version_id GROUP BY c.project_id"
    )
    for row in conn.execute(query):
        pid = int(row["project_id"])
        counts[pid] = counts.get(pid, 0) + int(row["n"])


def _folder(row: dict[str, object], target: Path | None) -> Path:
    root = str(row.get("root") or "")
    if root and Path(root).is_dir():
        return Path(root)
    if target is not None:
        return target.expanduser().resolve()
    raise Invalid(f"pick a folder for {row.get('name')}")


def _emit(bridge: Bridge) -> Emit:
    event = getattr(bridge, "_event", None)
    if not callable(event):
        raise Invalid("this bridge cannot record an import")
    return cast(Emit, event)


def _marked(root: Path, store: Path) -> bool:
    key = str(store.resolve())
    try:
        events = read_all(root)
    except LogCorrupt:
        return False
    return any(event.type == "import" and event.payload.get("store") == key for event in events)


def _import_project(store: Path, root: Path, project: str, project_id: int, emit: Emit) -> None:
    with _connect(store) as conn:
        paths = _lineage_paths(conn, project_id)
        versions = _versions(conn, project_id)
        verdicts = _verdicts(conn, project_id)
        notes = _notes(conn, project_id)
    files = tracked_files(root)
    snaps = Snapshots(root)
    for item in versions:
        rel = _relative(root, paths.get(str(item["lineage"])))
        if rel is None:
            continue
        body = _body(store, item["relpath"])
        if body is None:
            continue
        files[rel] = body
        author = item["author"]
        stamp = item["original_ts"]
        if not isinstance(author, str) or not isinstance(stamp, str):
            continue
        description = f"{author} {stamp} {rel}"
        made = snaps.snapshot(dict(files), description, author)
        version_id = made.id if made is not None else snaps.head().id
        emit(
            root,
            project,
            f"user:{author}",
            "version",
            {
                "imported_from": f"content:{item['id']}",
                "kind": "import",
                "original_ts": item["original_ts"],
                "path": rel,
                "version": version_id,
            },
        )
    for item in verdicts:
        emit(root, project, "user:local", "verdict", item)
    for item in notes:
        emit(root, project, "user:local", "annotation", item)
    emit(
        root,
        project,
        "user:local",
        "import",
        {"store": str(store.resolve()), "versions": len(versions)},
    )


def _lineage_paths(conn: sqlite3.Connection, project_id: int) -> dict[str, str]:
    found: dict[str, str] = {}
    if not _has(conn, "content"):
        return found
    rows = conn.execute(
        "SELECT lineage_id, attributes FROM content WHERE project_id = ? ORDER BY version_no",
        (project_id,),
    )
    for row in rows:
        attrs = _attrs(row["attributes"])
        resolved = attrs.get("resolved_path")
        if isinstance(resolved, str) and row["lineage_id"] not in found:
            found[str(row["lineage_id"])] = resolved
    return found


def _versions(conn: sqlite3.Connection, project_id: int) -> list[dict[str, object]]:
    if not _has(conn, "content"):
        return []
    rows = conn.execute(
        "SELECT id, lineage_id, version_no, created_at, attributes FROM content "
        "WHERE project_id = ? AND version_no > 0 ORDER BY created_at, version_no, id",
        (project_id,),
    )
    found: list[dict[str, object]] = []
    for row in rows:
        attrs = _attrs(row["attributes"])
        label = attrs.get("display_label")
        reason = attrs.get("snapshot_reason")
        author = label.strip() if isinstance(label, str) and label.strip() else ""
        if not author and isinstance(reason, str) and reason.strip():
            author = reason.strip()
        found.append(
            {
                "id": int(row["id"]),
                "lineage": str(row["lineage_id"]),
                "relpath": str(attrs.get("snapshot_relpath") or ""),
                "author": author or "import",
                "original_ts": _stamp(row["created_at"]),
            }
        )
    return found


def _verdicts(conn: sqlite3.Connection, project_id: int) -> list[dict[str, object]]:
    if not _has(conn, "content_changes"):
        return []
    rows = conn.execute(
        "SELECT id, intent_verdict, detected_at, affected_subject_id FROM content_changes "
        "WHERE project_id = ? AND intent_verdict IS NOT NULL AND intent_verdict != '' ORDER BY id",
        (project_id,),
    )
    return [
        {
            "imported_from": f"content_changes:{int(row['id'])}",
            "original_ts": _stamp(row["detected_at"]),
            "path": str(row["affected_subject_id"] or ""),
            "verdict": str(row["intent_verdict"]),
        }
        for row in rows
    ]


def _notes(conn: sqlite3.Connection, project_id: int) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    found.extend(_note_rows(conn, project_id, "paragraph_user_comments", "body"))
    found.extend(_note_rows(conn, project_id, "impact_annotations", "comment"))
    return found


def _note_rows(
    conn: sqlite3.Connection, project_id: int, table: str, column: str
) -> list[dict[str, object]]:
    if not _has(conn, table) or not _has(conn, "content"):
        return []
    query = (
        f"SELECT a.id AS id, a.{column} AS body, a.created_at AS created_at "  # noqa: S608
        f"FROM {table} AS a JOIN content AS c ON c.id = a.content_version_id "
        "WHERE c.project_id = ? ORDER BY a.id"
    )
    return [
        {
            "body": str(row["body"] or ""),
            "imported_from": f"{table}:{int(row['id'])}",
            "original_ts": _stamp(row["created_at"]),
        }
        for row in conn.execute(query, (project_id,))
    ]


def _relative(root: Path, resolved: object) -> str | None:
    if not isinstance(resolved, str) or not resolved:
        return None
    try:
        rel = Path(resolved).resolve().relative_to(root.resolve())
    except ValueError:
        return None
    text = rel.as_posix()
    if not text or text == "." or ".." in text.split("/"):
        return None
    return text


def _body(store: Path, relpath: object) -> bytes | None:
    if not isinstance(relpath, str) or not relpath:
        return None
    path = (store / relpath).resolve()
    try:
        path.relative_to(store.resolve())
    except ValueError:
        return None
    if not path.is_file():
        return None
    return path.read_bytes()


def _attrs(raw: object) -> dict[str, object]:
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _ident(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Invalid("a 1.x row has no id")
    return value


def _stamp(raw: object) -> str:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return ""
    return datetime.fromtimestamp(float(raw), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
