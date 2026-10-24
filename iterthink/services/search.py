"""Keyword search while typing, and meaning search for Enter. Local only."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from iterthink.services.bridge import LogEntry, SearchHit, kind_of
from iterthink.services.projects import tracked_files

if TYPE_CHECKING:
    from iterthink.services.indexer import Index

_ALIASES = {
    "doc": frozenset({"markdown", "text", "document"}),
    "plan": frozenset({"plan"}),
    "model": frozenset({"model"}),
    "table": frozenset({"table"}),
    "chat": frozenset({"chat"}),
    "app": frozenset({"app"}),
}
_TEXT = frozenset({"markdown", "table", "text"})
_DIM = 64
_RRF_K = 60


@dataclass(frozen=True)
class _Query:
    text: str
    kinds: frozenset[str] | None
    since: str | None
    history: bool
    filename: bool


def _parse(query: str) -> _Query:
    kind_match = re.search(r"\bkind:(\w+)", query, re.I)
    since_match = re.search(r"\bsince:(\d{4}-\d{2}-\d{2})", query, re.I)
    kinds = None
    if kind_match:
        word = kind_match.group(1).lower()
        kinds = _ALIASES.get(word, frozenset({word}))
    text = re.sub(r"\bin:history\b", " ", query, flags=re.I)
    text = re.sub(r"\bkind:\w+", " ", text, flags=re.I)
    text = re.sub(r"\bsince:\d{4}-\d{2}-\d{2}", " ", text, flags=re.I)
    text = re.sub(r"(?:^|\s)/[fp]\b", " ", text)
    text = re.sub(r"(?:^|\s)/p\s+\S+", " ", text)
    return _Query(
        " ".join(text.split()),
        kinds,
        since_match.group(1) if since_match else None,
        bool(re.search(r"\bin:history\b", query, re.I)),
        bool(re.search(r"(?:^|\s)/f\b", query)),
    )


def _ensure(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS ix_fts USING fts5("
        "body, path UNINDEXED, line UNINDEXED, kind UNINDEXED, scope UNINDEXED, ts UNINDEXED,"
        ' tokenize = "unicode61 remove_diacritics 2")'
    )
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS ix_trigram USING fts5("
        "body, path UNINDEXED, line UNINDEXED, kind UNINDEXED, scope UNINDEXED, ts UNINDEXED,"
        " tokenize = 'trigram')"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ix_chunk ("
        "id INTEGER PRIMARY KEY, path TEXT NOT NULL, line INTEGER NOT NULL, snippet TEXT NOT NULL)"
    )
    import sqlite_vec

    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS ix_vec USING vec0(embedding float[{_DIM}])")


def _fts_insert(
    conn: sqlite3.Connection, path: str, line: int, body: str, kind: str, scope: str, ts: str
) -> None:
    if not body.strip():
        return
    row = (body, path, line, kind, scope, ts)
    conn.execute(
        "INSERT INTO ix_fts (body, path, line, kind, scope, ts) VALUES (?, ?, ?, ?, ?, ?)",
        row,
    )
    conn.execute(
        "INSERT INTO ix_trigram (body, path, line, kind, scope, ts) VALUES (?, ?, ?, ?, ?, ?)",
        row,
    )


def _embed(text: str) -> list[float]:
    vector = [0.0] * _DIM
    for token in re.findall(r"\w+", text.casefold()):
        digest = hashlib.sha256(token.encode()).digest()
        vector[int.from_bytes(digest[:2], "big") % _DIM] += 1.0 if digest[2] % 2 == 0 else -1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _chunks(path: str, text: str) -> list[tuple[int, str]]:
    from iterthink.services.rag.chunking import build_parent_child_chunks, document_title

    parents = build_parent_child_chunks(text, doc_title=document_title(text, path))
    found = [
        (child.slot_index + 1, child.raw_text)
        for parent in parents
        for child in parent.children
        if child.raw_text.strip()
    ]
    return found or [(1, text)]


def _vectors(conn: sqlite3.Connection, path: str, text: str) -> None:
    import sqlite_vec

    for line, raw in _chunks(path, text):
        conn.execute(
            "INSERT INTO ix_chunk (path, line, snippet) VALUES (?, ?, ?)",
            (path, line, raw[:200]),
        )
        blob = sqlite_vec.serialize_float32(_embed(raw))
        conn.execute("INSERT INTO ix_vec (rowid, embedding) VALUES (?, ?)", (_rowid(conn), blob))


def _rowid(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT last_insert_rowid()").fetchone()
    return int(row[0]) if row is not None else 0


def _head_ts(project_dir: Path) -> str:
    folder = project_dir / ".iterthink" / "versions" / "snapshots"
    if not folder.is_dir():
        return ""
    stamps: list[str] = []
    for path in folder.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        if '"draft": true' in text or '"draft":true' in text:
            continue
        match = re.search(r'"ts":\s*"([^"]+)"', text)
        if match:
            stamps.append(match.group(1))
    return max(stamps) if stamps else ""


def fill_search(conn: sqlite3.Connection, project_dir: Path) -> None:
    """Rebuild FTS, trigram and local vectors from the current files and changes."""
    _ensure(conn)
    conn.execute("DELETE FROM ix_fts")
    conn.execute("DELETE FROM ix_trigram")
    conn.execute("DELETE FROM ix_chunk")
    conn.execute("DELETE FROM ix_vec")
    ts = _head_ts(project_dir)
    for path, data in sorted(tracked_files(project_dir).items()):
        kind = kind_of(path)
        _fts_insert(conn, path, 0, Path(path).name, kind, "latest", ts)
        if kind not in _TEXT:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            _fts_insert(conn, path, number, line, kind, "latest", ts)
        if text.strip():
            _vectors(conn, path, text)
    _history(conn, project_dir)


def _history(conn: sqlite3.Connection, project_dir: Path) -> None:
    from iterthink.services.proposals import reason_text

    rows = conn.execute(
        "SELECT affected_subject_id, from_value, to_value, ifnull(change_source,'')"
        " FROM content_changes"
    )
    for path, before, after, ts in rows:
        kind = kind_of(str(path))
        for text in (before, after):
            if isinstance(text, str):
                _fts_insert(conn, str(path), 0, text, kind, "history", str(ts))
    events = conn.execute("SELECT payload, ts FROM audit_events WHERE type = 'verdict'")
    for payload, ts in events:
        parsed: object = json.loads(str(payload))
        if not isinstance(parsed, dict):
            continue
        reason = reason_text(project_dir, parsed.get("reason"))
        _fts_insert(conn, "", 0, reason, "history", "history", str(ts))


def _filters(parsed: _Query, scope: str) -> tuple[str, list[object]]:
    sql = " AND scope = ?"
    args: list[object] = [scope]
    if parsed.kinds:
        marks = ",".join("?" for _ in parsed.kinds)
        sql += f" AND kind IN ({marks})"
        args.extend(sorted(parsed.kinds))
    if parsed.since:
        sql += " AND ts >= ?"
        args.append(parsed.since)
    if parsed.filename:
        sql += " AND line = 0"
    return sql, args


def _rows(
    conn: sqlite3.Connection, table: str, match: str, parsed: _Query, scope: str, limit: int
) -> list[SearchHit]:
    where, args = _filters(parsed, scope)
    if table == "ix_fts":
        statement = (
            "SELECT path, line, body FROM ix_fts WHERE ix_fts MATCH ?"  # noqa: S608
            + where
            + " ORDER BY bm25(ix_fts) LIMIT ?"
        )
    else:
        statement = (
            "SELECT path, line, body FROM ix_trigram WHERE ix_trigram MATCH ?"  # noqa: S608
            + where
            + " LIMIT ?"
        )
    try:
        found = conn.execute(statement, [match, *args, limit]).fetchall()
    except sqlite3.OperationalError:
        return []
    return [SearchHit(str(row[0]), int(row[1]), str(row[2]).strip()[:200]) for row in found]


def keyword(index: Index, project: str, query: str, limit: int) -> list[SearchHit]:
    """FTS5 BM25 plus a trigram pass for partial codes. Empty text returns nothing."""
    parsed = _parse(query)
    stored = index.project()
    if stored and stored != project:
        return []
    if not parsed.text:
        return []
    conn = index.conn
    scope = "history" if parsed.history else "latest"
    hits = _rows(conn, "ix_fts", parsed.text, parsed, scope, limit)
    if parsed.history or len(parsed.text) < 3:
        return hits[:limit]
    phrase = '"' + parsed.text.replace('"', " ") + '"'
    seen = {(hit.path, hit.line) for hit in hits}
    for hit in _rows(conn, "ix_trigram", phrase, parsed, scope, limit):
        if (hit.path, hit.line) not in seen:
            hits.append(hit)
            seen.add((hit.path, hit.line))
    return hits[:limit]


def semantic(index: Index, project: str, query: str, limit: int) -> list[SearchHit]:
    """Nearest chunks by a local vector. No model download and no remote call."""
    if not query.strip() or index.project() not in {"", project}:
        return []
    import sqlite_vec

    conn = index.conn
    _ensure(conn)
    blob = sqlite_vec.serialize_float32(_embed(query))
    try:
        rows = conn.execute(
            "SELECT rowid, distance FROM ix_vec WHERE embedding MATCH ? AND k = ?"
            " ORDER BY distance",
            (blob, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    hits: list[SearchHit] = []
    for row in rows:
        chunk = conn.execute(
            "SELECT path, line, snippet FROM ix_chunk WHERE id = ?", (int(row[0]),)
        ).fetchone()
        if chunk is not None:
            hits.append(SearchHit(str(chunk[0]), int(chunk[1]), str(chunk[2]).strip()[:200]))
    return hits


def hybrid(index: Index, project: str, query: str, limit: int) -> list[SearchHit]:
    """Reciprocal rank fusion of keyword and semantic lists. k = 60."""
    scores: dict[tuple[str, int], float] = {}
    best: dict[tuple[str, int], SearchHit] = {}
    width = max(limit, 50)
    for ranking in (keyword(index, project, query, width), semantic(index, project, query, width)):
        for rank, hit in enumerate(ranking):
            key = (hit.path, hit.line)
            scores[key] = scores.get(key, 0.0) + 1.0 / (_RRF_K + rank + 1)
            best.setdefault(key, hit)
    ordered = sorted(scores, key=lambda item: scores[item], reverse=True)
    return [best[item] for item in ordered[:limit]]


def indexed_search(
    state_dir: Path, root: Path, project: str, query: str, limit: int
) -> list[SearchHit]:
    """Bring the index up to date, then answer with keywords only."""
    from iterthink.services.indexer import index_for

    index = index_for(state_dir, project)
    index.update(root)
    return keyword(index, project, query, limit)


def indexed_log(state_dir: Path, root: Path, project: str, limit: int) -> list[LogEntry]:
    """Bring the index up to date, then read the log from it."""
    from iterthink.services.indexer import index_for, log_entries

    index = index_for(state_dir, project)
    index.update(root)
    return log_entries(index, root, limit)
