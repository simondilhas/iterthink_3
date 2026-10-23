"""Index projection: incremental update, proposals, conflicts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from iterthink.persistence.snapshots import Snapshots
from iterthink.services.bridge_real import RealBridge
from iterthink.services.event_log import append
from iterthink.services.indexer import Index

CONTRACT = "1.0.8"


def _bridge(tmp: Path) -> RealBridge:
    return RealBridge(state_dir=tmp / "state", machine="m-test")


def _make(tmp: Path, files: dict[str, str]) -> tuple[Path, str]:
    folder = tmp / "P"
    folder.mkdir()
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    info = _bridge(tmp).make_project(folder)
    return folder, info.id


def _rows(db: Path, sql: str) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(db)
    try:
        return list(conn.execute(sql))
    finally:
        conn.close()


def test_update_twice_is_noop(tmp_path: Path) -> None:
    folder, _project = _make(tmp_path, {"note.md": "hello\n"})
    index = Index(tmp_path / "index.db")
    index.rebuild(folder)
    digest = index.state_digest()
    first = index.update(folder)
    assert first.applied == 0
    assert first.replayed_from is None
    assert index.state_digest() == digest
    second = index.update(folder)
    assert second.applied == 0
    assert index.state_digest() == digest


def test_two_projects_never_mix(tmp_path: Path) -> None:
    from iterthink.services.search import keyword

    left = tmp_path / "A"
    right = tmp_path / "B"
    left.mkdir()
    right.mkdir()
    (left / "a.md").write_text("alphaunique\n", encoding="utf-8")
    (right / "b.md").write_text("betaunique\n", encoding="utf-8")
    bridge = _bridge(tmp_path)
    a_id = bridge.make_project(left).id
    b_id = bridge.make_project(right).id
    a_index = Index(tmp_path / "a.db")
    b_index = Index(tmp_path / "b.db")
    a_index.rebuild(left)
    b_index.rebuild(right)
    assert keyword(a_index, a_id, "alphaunique", 10)
    assert keyword(a_index, a_id, "betaunique", 10) == []
    assert keyword(b_index, b_id, "betaunique", 10)
    assert keyword(b_index, b_id, "alphaunique", 10) == []
    assert keyword(a_index, b_id, "alphaunique", 10) == []


def test_conflicting_accepts_surface_as_conflict(tmp_path: Path) -> None:
    folder, project = _make(tmp_path, {"note.md": "base\n"})
    snaps = Snapshots(folder)
    head = snaps.head().id
    first = snaps.draft(head, {"note.md": b"aaa\n"}, "proposed a", "agent:a")
    second = snaps.draft(head, {"note.md": b"bbb\n"}, "proposed b", "agent:b")
    for draft, pid in ((first, "pr-aaa1"), (second, "pr-bbb2")):
        append(
            folder,
            machine="m-test",
            actor="agent:a",
            type="proposal_created",
            project=project,
            payload={
                "id": pid,
                "baseline": head,
                "draft": draft.id,
                "paths": ["note.md"],
                "reason": "blob:none",
            },
            contract=CONTRACT,
        )
        append(
            folder,
            machine="m-test",
            actor="user:simon",
            type="verdict",
            project=project,
            payload={"proposal": pid, "verdict": "accepted", "reason": "blob:none"},
            contract=CONTRACT,
        )
    index = Index(tmp_path / "index.db")
    index.rebuild(folder)
    names = {
        str(name)
        for name, status in _rows(
            index.db_path, "SELECT name, status FROM content WHERE status = 'conflict'"
        )
    }
    assert names == {"pr-aaa1", "pr-bbb2"}


def test_proposal_is_candidate_row_with_proposes_relation(tmp_path: Path) -> None:
    folder, project = _make(tmp_path, {"note.md": "base\n"})
    made = _bridge(tmp_path).propose(project, {"note.md": "changed\n"}, "agent:a", "because")
    index = Index(tmp_path / "index.db")
    index.rebuild(folder)
    rows = _rows(
        index.db_path,
        "SELECT c.id, c.lineage_id, r.relation_type "
        "FROM content c JOIN content_relations r ON r.source_content_id = c.id "
        "WHERE c.status = 'candidate'",
    )
    assert len(rows) == 1
    assert rows[0][1] == "note.md"
    assert rows[0][2] == "proposes"
    assert made.id
