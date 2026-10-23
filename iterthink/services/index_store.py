"""Content, relation and change rows for one project index."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from iterthink.compare.engines import diff
from iterthink.contract.enums import (
    CANONICAL_TYPE_ARTIFACT,
    CHANGE_CLASS_PROPERTY,
    CHANGE_TYPE_PROPERTY,
    CONTENT_KIND_ARTIFACT,
    PROPERTY_PATH_KIND_DOCUMENT,
)
from iterthink.contract.version import CANONICAL_TYPE_VERSION
from iterthink.persistence.snapshots import Snapshots
from iterthink.services.bridge import kind_of
from iterthink.services.event_log import Event


def _cid(*parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode()).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


def _rowid(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT last_insert_rowid()").fetchone()
    return int(row[0]) if row is not None else 0


def _manifests(project_dir: Path) -> list[dict[str, object]]:
    folder = project_dir / ".iterthink" / "versions" / "snapshots"
    if not folder.is_dir():
        return []
    found: list[dict[str, object]] = []
    for path in sorted(folder.glob("*.json")):
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(parsed, dict) and isinstance(parsed.get("files"), dict):
            found.append(parsed)
    found.sort(key=lambda item: (str(item.get("ts")), str(item.get("id"))))
    return found


def _bytes_at(snaps: Snapshots, version: str, path: str) -> bytes | None:
    try:
        return snaps.file_at(version, path)
    except (OSError, ValueError):
        return None


def _clear_content(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM content_relations")
    conn.execute("DELETE FROM content_file_links")
    conn.execute("DELETE FROM content_changes")
    conn.execute("DELETE FROM content")
    conn.execute("DELETE FROM files")
    conn.execute("PRAGMA foreign_keys = ON")


def _content(
    conn: sqlite3.Connection,
    lineage: str,
    version_no: int,
    source: str,
    status: str | None,
    name: str | None,
    kind: str,
) -> int:
    conn.execute(
        "INSERT INTO content (workspace_id, project_id, contract_id, content_kind, canonical_type,"
        " canonical_type_version, lineage_id, version_no, is_latest, is_deleted, status, name,"
        " source_id, created_at, updated_at) VALUES (1, 1, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, 0, 0)",
        (
            _cid(lineage, str(version_no), status or "", source, name or ""),
            kind,
            CANONICAL_TYPE_ARTIFACT,
            CANONICAL_TYPE_VERSION,
            lineage,
            version_no,
            status,
            name,
            source or None,
        ),
    )
    return _rowid(conn)


def _link(conn: sqlite3.Connection, content_id: int, path: str) -> None:
    row = conn.execute("SELECT id FROM files WHERE storage_relpath = ?", (path,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO files (workspace_id, project_id, storage_relpath, created_at)"
            " VALUES (1, 1, ?, 0)",
            (path,),
        )
        file_id = _rowid(conn)
    else:
        file_id = int(row[0])
    conn.execute(
        "INSERT INTO content_file_links (workspace_id, project_id, content_id, file_id,"
        " relation_type, is_primary, created_at) VALUES (1, 1, ?, ?, 'source_file', 1, 0)",
        (content_id, file_id),
    )


def _relate(conn: sqlite3.Connection, source: int, target: int, kind: str) -> None:
    conn.execute(
        "INSERT INTO content_relations (workspace_id, project_id, source_content_id,"
        " target_content_id, relation_type, lineage_id, version_no, is_latest, created_at,"
        " updated_at) VALUES (1, 1, ?, ?, ?, ?, 1, 1, 0, 0)",
        (source, target, kind, f"{kind}:{source}:{target}"),
    )


def _change(
    conn: sqlite3.Connection,
    content_id: int,
    path: str,
    prev: int,
    version_no: int,
    prop: str,
    before: str | None,
    after: str | None,
    ts: str,
) -> None:
    conn.execute(
        "INSERT INTO content_changes (workspace_id, project_id, content_version_id, lineage_id,"
        " change_class, change_type, from_revision, to_revision, affected_subject_id,"
        " affected_subject_type, property_path, property_path_kind, from_value, to_value,"
        " detected_at, change_source) VALUES (1, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
        (
            content_id,
            path,
            CHANGE_CLASS_PROPERTY,
            CHANGE_TYPE_PROPERTY,
            prev,
            version_no,
            path,
            kind_of(path),
            prop,
            PROPERTY_PATH_KIND_DOCUMENT,
            before,
            after,
            ts,
        ),
    )


def _record_diff(
    conn: sqlite3.Connection,
    path: str,
    before: bytes | None,
    after: bytes | None,
    content_id: int,
    prev: int,
    version_no: int,
    ts: str,
) -> None:
    result = diff(path, before, after)
    blocks = [
        block for block in result.blocks if block.kind != "stable" and (block.before or block.after)
    ]
    for index, block in enumerate(blocks):
        _change(
            conn,
            content_id,
            path,
            prev,
            version_no,
            f"block:{index}",
            block.before,
            block.after,
            ts,
        )
    for cell in result.cell_changes:
        _change(conn, content_id, path, prev, version_no, cell.column, cell.before, cell.after, ts)


def _versions(conn: sqlite3.Connection, project_dir: Path) -> dict[tuple[str, str], int]:
    snaps = Snapshots(project_dir)
    prev_digest: dict[str, str] = {}
    prev_bytes: dict[str, bytes] = {}
    numbers: dict[str, int] = {}
    latest: dict[str, int] = {}
    ids: dict[tuple[str, str], int] = {}
    for manifest in _manifests(project_dir):
        if manifest.get("draft") is True:
            continue
        snap_id = str(manifest["id"])
        ts = str(manifest.get("ts") or "")
        files = manifest["files"]
        if not isinstance(files, dict):
            continue
        for path in sorted(str(item) for item in files):
            digest = files.get(path)
            if not isinstance(digest, str) or prev_digest.get(path) == digest:
                continue
            data = _bytes_at(snaps, snap_id, path) or b""
            numbers[path] = numbers.get(path, 0) + 1
            content_id = _content(
                conn, path, numbers[path], snap_id, None, None, CONTENT_KIND_ARTIFACT
            )
            ids[(snap_id, path)] = content_id
            if path in latest:
                conn.execute("UPDATE content SET is_latest = 0 WHERE id = ?", (latest[path],))
            conn.execute("UPDATE content SET is_latest = 1 WHERE id = ?", (content_id,))
            latest[path] = content_id
            _link(conn, content_id, path)
            _record_diff(
                conn,
                path,
                prev_bytes.get(path),
                data,
                content_id,
                numbers[path] - 1,
                numbers[path],
                ts,
            )
            prev_digest[path] = digest
            prev_bytes[path] = data
    return ids


def _next_number(conn: sqlite3.Connection, path: str) -> int:
    row = conn.execute(
        "SELECT max(version_no) FROM content WHERE lineage_id = ?", (path,)
    ).fetchone()
    return int(row[0] or 0) + 1 if row is not None else 1


def _proposals(
    conn: sqlite3.Connection,
    project_dir: Path,
    versions: dict[tuple[str, str], int],
    events: list[Event],
) -> None:
    snaps = Snapshots(project_dir)
    baselines: dict[str, str] = {}
    for event in events:
        if event.type != "proposal_created":
            continue
        pid = str(event.payload.get("id") or "")
        baseline = str(event.payload.get("baseline") or "")
        draft = str(event.payload.get("draft") or "")
        paths = event.payload.get("paths")
        baselines[pid] = baseline
        if not isinstance(paths, list):
            continue
        for path in paths:
            if not isinstance(path, str):
                continue
            number = _next_number(conn, path)
            content_id = _content(
                conn, path, number, draft, "candidate", pid, CONTENT_KIND_ARTIFACT
            )
            target = versions.get((baseline, path))
            if target is not None:
                _relate(conn, content_id, target, "proposes")
            _record_diff(
                conn,
                path,
                _bytes_at(snaps, baseline, path),
                _bytes_at(snaps, draft, path),
                content_id,
                number - 1,
                number,
                event.ts,
            )
    _verdicts(conn, events, baselines)


def _verdicts(conn: sqlite3.Connection, events: list[Event], baselines: dict[str, str]) -> None:
    accepted: dict[str, list[str]] = {}
    for event in events:
        if event.type != "verdict":
            continue
        pid = str(event.payload.get("proposal") or "")
        word = event.payload.get("verdict")
        if word not in {"accepted", "rejected"}:
            continue
        conn.execute(
            "UPDATE content_changes SET intent_verdict = ? WHERE content_version_id IN"
            " (SELECT id FROM content WHERE name = ?)",
            (str(word), pid),
        )
        if word == "accepted" and pid in baselines:
            accepted.setdefault(baselines[pid], []).append(pid)
    for pids in accepted.values():
        unique = list(dict.fromkeys(pids))
        if len(unique) < 2:
            continue
        for pid in unique:
            conn.execute(
                "UPDATE content SET status = 'conflict' WHERE name = ? AND status = 'candidate'",
                (pid,),
            )


def _contains(conn: sqlite3.Connection, project: str, folder_name: str) -> None:
    source = _content(conn, f"project:{project}", 1, project, None, folder_name, "project")
    conn.execute("UPDATE content SET is_latest = 1 WHERE id = ?", (source,))
    rows = conn.execute(
        "SELECT id FROM content WHERE is_latest = 1 AND lineage_id != ?",
        (f"project:{project}",),
    )
    for row in rows:
        _relate(conn, source, int(row[0]), "contains")


def write_projection(
    conn: sqlite3.Connection, project_dir: Path, events: list[Event], project: str
) -> None:
    """Replace content rows from snapshots, files and proposal events."""
    _clear_content(conn)
    versions = _versions(conn, project_dir)
    _proposals(conn, project_dir, versions, events)
    _contains(conn, project, project_dir.name)
