"""Tests for the test harness itself, so agents can trust the fixtures."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from .conftest import FixedClock, snapshot_sources


def test_project_dir_has_sources_with_non_ascii_names(project_dir: Path) -> None:
    names = set(snapshot_sources(project_dir))
    assert {"Pflichtenheft.md", "Türliste.csv", "Pläne/Notiz Grundriss EG.md"} <= names


def test_source_snapshot_ignores_iterthink_and_jj(project_dir: Path) -> None:
    before = snapshot_sources(project_dir)
    (project_dir / ".iterthink" / "log").mkdir(parents=True)
    (project_dir / ".iterthink" / "log" / "m-1.jsonl").write_text("{}\n", encoding="utf-8")
    (project_dir / ".jj").mkdir()
    (project_dir / ".jj" / "x").write_text("x", encoding="utf-8")
    assert snapshot_sources(project_dir) == before


def test_source_snapshot_detects_a_changed_byte(project_dir: Path) -> None:
    before = snapshot_sources(project_dir)
    path = project_dir / "Türliste.csv"
    path.write_bytes(path.read_bytes().replace(b"EI30", b"EI60"))
    assert snapshot_sources(project_dir) != before


def test_projects_are_separate(project_dir: Path, second_project_dir: Path) -> None:
    assert project_dir.parent == second_project_dir.parent
    assert not set(snapshot_sources(project_dir)) & set(snapshot_sources(second_project_dir))


def test_network_is_blocked_by_default() -> None:
    with socket.socket() as s, pytest.raises(RuntimeError, match="offline"):
        s.connect(("192.0.2.1", 443))  # TEST-NET-1, never routed


def test_fixed_clock_is_deterministic(fixed_clock: FixedClock) -> None:
    first, second = fixed_clock(), fixed_clock()
    assert (second - first).total_seconds() == 1
    assert first.isoformat() == "2026-10-23T05:00:00+00:00"
