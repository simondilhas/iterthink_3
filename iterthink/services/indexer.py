"""Rebuildable index. Files, versions and the log are the source; SQLite is a projection."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from iterthink.services.bridge import LogEntry
from iterthink.services.event_log import Event, read_all
from iterthink.services.projects import settings_of
from iterthink.services.proposals import describe

INDEX_VERSION = "1"
_LOCKS: dict[str, threading.Lock] = {}
_GUARD = threading.Lock()


@dataclass(frozen=True)
class UpdateResult:
    """How many events this call applied, and which snapshot a late event replayed."""

    applied: int
    replayed_from: str | None


def _lock(path: Path) -> threading.Lock:
    with _GUARD:
        lock = _LOCKS.get(str(path))
        if lock is None:
            lock = threading.Lock()
            _LOCKS[str(path)] = lock
        return lock


def _key(event: Event) -> str:
    return f"{event.ts}\t{event.machine}\t{event.seq:010d}"


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _create_db(path: Path) -> None:
    from sqlalchemy import create_engine

    from iterthink.db import models as _models  # noqa: F401
    from iterthink.db.base import Base

    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    conn = _connect(path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS index_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY,
            event_hash TEXT NOT NULL UNIQUE,
            seq INTEGER NOT NULL,
            ts TEXT NOT NULL,
            machine TEXT NOT NULL,
            actor TEXT NOT NULL,
            type TEXT NOT NULL,
            project TEXT NOT NULL,
            payload TEXT NOT NULL,
            contract TEXT NOT NULL
        );
        """
    )
    conn.execute("INSERT INTO index_meta(key, value) VALUES ('index_version', ?)", (INDEX_VERSION,))
    conn.commit()
    conn.close()


def _token(project_dir: Path) -> str:
    parts: list[str] = []
    log_dir = project_dir / ".iterthink" / "log"
    if log_dir.is_dir():
        for path in sorted(log_dir.glob("*.jsonl")):
            parts.append(f"log:{path.name}:{hashlib.sha256(path.read_bytes()).hexdigest()}")
    snap_dir = project_dir / ".iterthink" / "versions" / "snapshots"
    if snap_dir.is_dir():
        parts.extend(f"snap:{path.name}" for path in sorted(snap_dir.glob("*.json")))
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _project_id(project_dir: Path) -> str:
    raw = settings_of(project_dir).get("id")
    return raw if isinstance(raw, str) and raw else project_dir.name


class Index:
    """One SQLite file for one project. `rebuild` and `update` converge."""

    def __init__(self, db_path: Path, checkpoint_every: int = 500) -> None:
        self.db_path = db_path
        self.checkpoint_every = checkpoint_every
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            _create_db(self.db_path)
        self.conn = _connect(self.db_path)
        if self.meta("index_version") != INDEX_VERSION:
            self._reset()

    def close(self) -> None:
        self.conn.close()

    def meta(self, key: str) -> str | None:
        try:
            row = self.conn.execute("SELECT value FROM index_meta WHERE key = ?", (key,)).fetchone()
        except sqlite3.Error:
            return None
        return None if row is None else str(row[0])

    def project(self) -> str:
        return self.meta("project") or ""

    def rebuild(self, project_dir: Path) -> None:
        """Drop the index and project the folder again."""
        with _lock(self.db_path):
            self._reset()
            events = read_all(project_dir)
            self._apply_audit(events)
            self._refresh(project_dir, events)
            self._remember(project_dir)
            if events and len(events) >= self.checkpoint_every:
                self._checkpoint(self.meta("watermark") or "")

    def update(self, project_dir: Path) -> UpdateResult:
        """Apply new events. A late event replays from the newest snapshot below it."""
        with _lock(self.db_path):
            events = read_all(project_dir)
            fresh, token = self._fresh(events, project_dir)
            if fresh is None:
                return UpdateResult(0, None)
            replayed: str | None = None
            mark = self.meta("watermark") or ""
            late = [event for event in fresh if mark and _key(event) < mark]
            if late:
                fresh, replayed = self._replay(events, min(_key(event) for event in late))
            applied = self._apply_audit(fresh)
            self._refresh(project_dir, events)
            self._remember(project_dir, token)
            if applied >= self.checkpoint_every:
                self._checkpoint(self.meta("watermark") or "")
            return UpdateResult(applied, replayed)

    def state_digest(self) -> str:
        """Stable hash of the projection. Autoincrement ids are not part of it."""
        queries = (
            "SELECT lineage_id, version_no, ifnull(status,''), is_latest, ifnull(name,''),"
            " ifnull(source_id,''), content_kind FROM content ORDER BY 1,2,3,4",
            "SELECT r.relation_type, s.lineage_id, s.version_no, t.lineage_id, t.version_no"
            " FROM content_relations r JOIN content s ON s.id = r.source_content_id"
            " JOIN content t ON t.id = r.target_content_id ORDER BY 1,2,3,4,5",
            "SELECT lineage_id, from_revision, to_revision, ifnull(property_path,''),"
            " ifnull(from_value,''), ifnull(to_value,''), ifnull(intent_verdict,'')"
            " FROM content_changes ORDER BY 1,2,3,4,5,6,7",
            "SELECT event_hash, seq, ts, machine, type FROM audit_events ORDER BY 1",
        )
        parts = [json.dumps([tuple(row) for row in self.conn.execute(query)]) for query in queries]
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()

    def _fresh(self, events: list[Event], project_dir: Path) -> tuple[list[Event] | None, str]:
        have = {str(row[0]) for row in self.conn.execute("SELECT event_hash FROM audit_events")}
        fresh = [event for event in events if event.hash not in have]
        token = _token(project_dir)
        if not fresh and token == (self.meta("token") or ""):
            return None, token
        return fresh, token

    def _remember(self, project_dir: Path, token: str | None = None) -> None:
        self._set("token", token if token is not None else _token(project_dir))
        self._set("watermark", _watermark(self.conn))
        self._set("project", _project_id(project_dir))
        self.conn.commit()

    def _set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO index_meta(key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def _reset(self) -> None:
        self.conn.close()
        self.db_path.unlink(missing_ok=True)
        for extra in ("-wal", "-shm"):
            Path(str(self.db_path) + extra).unlink(missing_ok=True)
        for snap in self._snaps():
            snap.unlink(missing_ok=True)
        _create_db(self.db_path)
        self.conn = _connect(self.db_path)

    def _snaps(self) -> list[Path]:
        return sorted(self.db_path.parent.glob(f"{self.db_path.name}.*.snap"))

    def _checkpoint(self, watermark: str) -> None:
        self._set("watermark", watermark)
        self.conn.commit()
        number = int(self.meta("snap_seq") or "0") + 1
        dest = self.db_path.with_name(f"{self.db_path.name}.{number}.snap")
        dest.unlink(missing_ok=True)
        self.conn.isolation_level = None
        quoted = str(dest).replace("'", "''")
        self.conn.execute(f"VACUUM INTO '{quoted}'")
        self.conn.isolation_level = "DEFERRED"
        self._set("snap_seq", str(number))
        self.conn.commit()
        ranked = sorted(self._snaps(), key=_snap_mark)
        for path in ranked[:-3]:
            path.unlink(missing_ok=True)

    def _restore(self, snap: Path) -> None:
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.conn.close()
        for extra in ("-wal", "-shm"):
            Path(str(self.db_path) + extra).unlink(missing_ok=True)
        shutil.copyfile(snap, self.db_path)
        self.conn = _connect(self.db_path)

    def _replay(self, events: list[Event], border: str) -> tuple[list[Event], str]:
        snap = _snapshot_below(self._snaps(), border)
        if snap is None:
            self._wipe()
            origin = "start"
        else:
            self._restore(snap)
            origin = snap.name
        have = {str(row[0]) for row in self.conn.execute("SELECT event_hash FROM audit_events")}
        return [event for event in events if event.hash not in have], origin

    def _wipe(self) -> None:
        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.conn.execute("DELETE FROM content_relations")
        self.conn.execute("DELETE FROM content_file_links")
        self.conn.execute("DELETE FROM content_changes")
        self.conn.execute("DELETE FROM content")
        self.conn.execute("DELETE FROM files")
        self.conn.execute("DELETE FROM audit_events")
        self.conn.execute("PRAGMA foreign_keys = ON")

    def _apply_audit(self, events: list[Event]) -> int:
        applied = 0
        for event in events:
            payload = json.dumps(
                event.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            cursor = self.conn.execute(
                "INSERT INTO audit_events (event_hash, seq, ts, machine, actor, type, project,"
                " payload, contract) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(event_hash) DO NOTHING",
                (
                    event.hash,
                    event.seq,
                    event.ts,
                    event.machine,
                    event.actor,
                    event.type,
                    event.project,
                    payload,
                    event.contract,
                ),
            )
            applied += cursor.rowcount
        return applied

    def _refresh(self, project_dir: Path, events: list[Event]) -> None:
        from iterthink.services.index_store import write_projection
        from iterthink.services.search import fill_search

        write_projection(self.conn, project_dir, events, _project_id(project_dir))
        fill_search(self.conn, project_dir)
        self.conn.commit()


def _watermark(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT ts, machine, seq FROM audit_events ORDER BY ts DESC, machine DESC, seq DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return ""
    return f"{row['ts']}\t{row['machine']}\t{int(row['seq']):010d}"


def _snap_mark(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("SELECT value FROM index_meta WHERE key = 'watermark'").fetchone()
    except sqlite3.Error:
        return ""
    finally:
        conn.close()
    return "" if row is None else str(row[0])


def _snapshot_below(snaps: list[Path], border: str) -> Path | None:
    best: Path | None = None
    mark = ""
    for path in snaps:
        current = _snap_mark(path)
        if current and current < border and current >= mark:
            best, mark = path, current
    return best


def log_entries(index: Index, root: Path, limit: int) -> list[LogEntry]:
    """Newest log rows, sentences included, read from the projection."""
    rows = index.conn.execute(
        "SELECT seq, ts, machine, actor, type, payload, event_hash FROM audit_events"
        " ORDER BY ts DESC, machine DESC, seq DESC LIMIT ?",
        (limit,),
    ).fetchall()
    found: list[LogEntry] = []
    for row in rows:
        payload: object = json.loads(str(row["payload"]))
        body = payload if isinstance(payload, dict) else {}
        found.append(
            LogEntry(
                seq=int(row["seq"]),
                ts=str(row["ts"]),
                machine=str(row["machine"]),
                actor=str(row["actor"]),
                type=str(row["type"]),
                summary=describe(root, str(row["type"]), body),
                hash=str(row["event_hash"]),
            )
        )
    return found


def index_for(state_dir: Path, project: str) -> Index:
    """The machine-local database for `project`."""
    return Index(state_dir / "index" / f"{project}.db")


def schedule_index(state_dir: Path, project: str, root: Path) -> None:
    """Index after an event without making the caller wait. Quiet under pytest."""
    import os

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return

    def work() -> None:
        try:
            index_for(state_dir, project).update(root)
        except (OSError, sqlite3.Error):
            return

    threading.Thread(target=work, name="iterthink-index", daemon=True).start()
