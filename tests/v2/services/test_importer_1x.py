"""A 1.x store becomes snapshots and decision-log events."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from iterthink import config
from iterthink.db.base import Base
from iterthink.db.change_models import ContentChange
from iterthink.db.content_models import Content
from iterthink.db.models import ParagraphUserComment
from iterthink.db.session import get_engine, reset_engine_cache, session_scope
from iterthink.db.workspace import Project
from iterthink.persistence.content_repo import persist_version_snapshot
from iterthink.services.bridge_real import RealBridge
from iterthink.services.event_log import read_all
from iterthink.services.importer_1x import preview, run_import

NOTE = "note.md"
WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _clock() -> datetime:
    return WHEN


def _digest(store: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(store.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(store).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _checkpoint(store: Path) -> None:
    reset_engine_cache()
    conn = sqlite3.connect(store / "store.sqlite3")
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _build(tmp_path: Path, project_dir: Path) -> Path:
    store = tmp_path / "store"
    store.mkdir()
    saved = (config.STORE_DIR, config.STORE_DB_PATH, config.RAG_DB_PATH)
    config.STORE_DIR = store
    config.STORE_DB_PATH = store / "store.sqlite3"
    config.RAG_DB_PATH = store / "store.rag.sqlite3"
    reset_engine_cache()
    try:
        Base.metadata.create_all(get_engine())
        note = project_dir / NOTE
        note.write_text("zwei\n", encoding="utf-8")
        with session_scope() as session:
            session.add(
                Project(
                    workspace_id=1,
                    name=project_dir.name,
                    root_path=str(project_dir.resolve()),
                )
            )
            session.flush()
            persist_version_snapshot(session, note, "eins\n", "manual", display_label="ada")
            second = persist_version_snapshot(
                session, note, "zwei\n", "manual", display_label="bea"
            )
            rows = session.scalars(
                select(Content).where(Content.version_no > 0).order_by(Content.version_no)
            ).all()
            rows[0].created_at, rows[1].created_at = 1_600_000_000, 1_600_001_000
            assert second is not None
            session.add(
                ContentChange(
                    workspace_id=1,
                    project_id=1,
                    content_version_id=second,
                    lineage_id=rows[1].lineage_id,
                    change_class="PropertyChange",
                    change_type="edit",
                    from_revision=1,
                    to_revision=2,
                    affected_subject_id=NOTE,
                    affected_subject_type="document",
                    intent_verdict="accepted",
                    detected_at=1_600_002_000,
                )
            )
            session.add(
                ParagraphUserComment(
                    content_version_id=second,
                    paragraph_index=0,
                    body="check the door",
                    created_at=1_600_003_000,
                    updated_at=1_600_003_000,
                )
            )
    finally:
        _checkpoint(store)
        config.STORE_DIR, config.STORE_DB_PATH, config.RAG_DB_PATH = saved
        reset_engine_cache()
    return store


def _bridge(tmp_path: Path) -> RealBridge:
    return RealBridge(state_dir=tmp_path / "state", machine="m-test", now=_clock)


def test_versions_imported_in_order_with_authors(tmp_path: Path, project_dir: Path) -> None:
    store = _build(tmp_path, project_dir)
    counts = preview(store)
    assert counts[0]["versions"] == 2
    bridge = _bridge(tmp_path)
    project = run_import(store, bridge)[0]
    imported = [item for item in bridge.history(project, NOTE) if item.actor in {"ada", "bea"}]
    assert [item.actor for item in imported] == ["bea", "ada"]
    assert imported[0].message.startswith("bea ")
    assert imported[1].message.startswith("ada ")
    events = [
        event
        for event in read_all(project_dir)
        if event.type == "version" and event.payload.get("imported_from")
    ]
    assert len(events) == 2
    assert events[0].ts.startswith("2026-01-01")
    assert events[0].payload["original_ts"] != events[0].ts
    assert str(events[1].payload["original_ts"]).startswith("2020-")


def test_verdicts_become_events_and_log_verifies(tmp_path: Path, project_dir: Path) -> None:
    store = _build(tmp_path, project_dir)
    bridge = _bridge(tmp_path)
    project = run_import(store, bridge)[0]
    events = read_all(project_dir)
    verdicts = [
        event
        for event in events
        if str(event.payload.get("imported_from", "")).startswith("content_changes:")
    ]
    notes = [
        event
        for event in events
        if str(event.payload.get("imported_from", "")).startswith("paragraph_user_comments:")
    ]
    assert verdicts
    assert verdicts[0].payload.get("original_ts")
    assert notes
    assert notes[0].payload.get("body") == "check the door"
    assert bridge.verify(project).ok


def test_import_is_idempotent(tmp_path: Path, project_dir: Path) -> None:
    store = _build(tmp_path, project_dir)
    bridge = _bridge(tmp_path)
    project = run_import(store, bridge)[0]
    before = (len(read_all(project_dir)), len(bridge.history(project)))
    again = run_import(store, bridge)
    assert again == []
    assert (len(read_all(project_dir)), len(bridge.history(project))) == before


def test_store_unchanged_after_import(tmp_path: Path, project_dir: Path) -> None:
    store = _build(tmp_path, project_dir)
    before = _digest(store)
    run_import(store, _bridge(tmp_path))
    assert _digest(store) == before
