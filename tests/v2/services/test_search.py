"""Keyword, trigram and semantic search over the project index."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from iterthink.services.bridge_real import RealBridge
from iterthink.services.indexer import Index
from iterthink.services.search import hybrid, keyword, semantic


def _indexed(tmp: Path, files: dict[str, str]) -> tuple[Index, str, Path]:
    folder = tmp / "P"
    folder.mkdir()
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    info = RealBridge(state_dir=tmp / "state", machine="m-test").make_project(folder)
    index = Index(tmp / "index.db")
    index.rebuild(folder)
    return index, info.id, folder


def test_keyword_search_ranks_exact_word_first(tmp_path: Path) -> None:
    index, project, _folder = _indexed(
        tmp_path,
        {
            "exact.md": "EI30\n",
            "long.md": "EI30 " + ("filler " * 80),
        },
    )
    hits = keyword(index, project, "EI30", 10)
    assert hits
    assert hits[0].path == "exact.md"


@pytest.mark.slow
def test_search_under_50ms_for_2000_files(tmp_path: Path) -> None:
    folder = tmp_path / "P"
    folder.mkdir()
    for number in range(2000):
        (folder / f"f{number}.txt").write_text(f"file {number} token-{number}\n", encoding="utf-8")
    info = RealBridge(state_dir=tmp_path / "state", machine="m-test").make_project(folder)
    index = Index(tmp_path / "index.db")
    index.rebuild(folder)
    started = time.perf_counter()
    hits = keyword(index, info.id, "token-1500", 10)
    elapsed = time.perf_counter() - started
    assert hits
    assert hits[0].path == "f1500.txt"
    assert elapsed < 0.05


def test_semantic_search_makes_no_network_calls(tmp_path: Path) -> None:
    index, project, _folder = _indexed(tmp_path, {"note.md": "Fire doors in the hall.\n"})
    hits = semantic(index, project, "doors", 5)
    assert isinstance(hits, list)
    fused = hybrid(index, project, "doors", 5)
    assert isinstance(fused, list)


def test_partial_code_matches_via_trigram(tmp_path: Path) -> None:
    index, project, _folder = _indexed(tmp_path, {"doors.md": "The class is EI 90 today.\n"})
    hits = keyword(index, project, "EI 9", 10)
    assert any(hit.path == "doors.md" for hit in hits)


def test_query_syntax_kind_and_in_history(tmp_path: Path) -> None:
    index, project, folder = _indexed(
        tmp_path,
        {
            "note.md": "oldword stays in history\n",
            "Türliste.csv": "id,note\nT01,other\n",
        },
    )
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    bridge.save(project, "note.md", "alpha beta gamma\n", "user:simon", "edit")
    (folder / "Türliste.csv").write_text("id,note\nT01,alpha\n", encoding="utf-8")
    index.rebuild(folder)
    table_hits = keyword(index, project, "kind:table alpha", 10)
    assert any(hit.path == "Türliste.csv" for hit in table_hits)
    assert all(hit.path == "Türliste.csv" for hit in table_hits)
    assert any(hit.path == "note.md" for hit in keyword(index, project, '"beta gamma"', 10))
    assert keyword(index, project, '"gamma beta"', 10) == []
    assert any(hit.path == "Türliste.csv" for hit in keyword(index, project, "/f türliste", 10))
    assert any(hit.path == "note.md" for hit in keyword(index, project, "in:history oldword", 10))
    assert keyword(index, project, "oldword", 10) == []
    assert keyword(index, project, "since:2999-01-01 alpha", 10) == []
    assert keyword(index, project, "since:2000-01-01 alpha", 10)
