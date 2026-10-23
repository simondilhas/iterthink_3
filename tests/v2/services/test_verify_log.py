"""Acceptance tests for standalone log verification (slice A2)."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from iterthink.services.event_log import append, checkpoint
from iterthink.services.verify_log import main, verify, verify_all

CONTRACT = "1.0.8"
SCRIPT = Path(__file__).resolve().parents[3] / "iterthink" / "services" / "verify_log.py"


def _now_at(*stamps: str) -> Callable[[], datetime]:
    pending = list(stamps)

    def now() -> datetime:
        raw = pending.pop(0)
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)

    return now


def _append(project_dir: Path, machine: str, stamp: str, text: str = "hello") -> Any:
    return append(
        project_dir,
        machine=machine,
        actor="user:simon",
        type="note",
        project="p-19c2",
        payload={"text": text},
        contract=CONTRACT,
        now=_now_at(stamp),
    )


def _log(project_dir: Path, machine: str) -> Path:
    return project_dir / ".iterthink" / "log" / f"{machine}.jsonl"


def _three(project_dir: Path) -> Path:
    _append(project_dir, "m-a", "2026-10-23T05:00:01Z", "alpha")
    _append(project_dir, "m-a", "2026-10-23T05:00:02Z", "bravo")
    _append(project_dir, "m-a", "2026-10-23T05:00:03Z", "charlie")
    return _log(project_dir, "m-a")


def test_verify_detects_edit(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    log = _three(project)
    log.write_bytes(log.read_bytes().replace(b"bravo", b"bravX", 1))
    result = verify(log)
    assert result.ok is False
    assert result.error_line == 2
    assert "hash" in result.reason


def test_verify_detects_removed_line(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    log = _three(project)
    lines = log.read_text(encoding="utf-8").splitlines()
    log.write_text(lines[0] + "\n" + lines[2] + "\n", encoding="utf-8")
    result = verify(log)
    assert result.ok is False
    assert result.error_line == 2
    assert "prev_hash" in result.reason


def test_verify_detects_reordered_lines(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    log = _three(project)
    lines = log.read_text(encoding="utf-8").splitlines()
    log.write_text("\n".join((lines[0], lines[2], lines[1])) + "\n", encoding="utf-8")
    result = verify(log)
    assert result.ok is False
    assert result.error_line == 2
    assert "prev_hash" in result.reason


def test_verify_detects_incomplete_last_line(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    log = _three(project)
    log.write_bytes(log.read_bytes()[:-1])
    result = verify(log)
    assert result.ok is False
    assert result.error_line == 3
    assert "incomplete" in result.reason


def test_verify_all_detects_edit_in_other_log_via_checkpoint(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    _append(project, "m-b", "2026-10-23T05:00:01Z", "other")
    _append(project, "m-a", "2026-10-23T05:00:02Z", "local")
    checkpoint(
        project,
        machine="m-a",
        actor="user:simon",
        project="p-19c2",
        contract=CONTRACT,
        now=_now_at("2026-10-23T05:00:03Z"),
    )
    other = _log(project, "m-b")
    other.unlink()
    _append(project, "m-b", "2026-10-23T05:00:04Z", "replaced")
    assert verify(_log(project, "m-a")).ok is True
    assert verify(other).ok is True
    result = verify_all(project)
    assert result.ok is False
    assert result.error_line == 2
    assert "checkpoint" in result.reason


def test_verify_script_runs_with_stdlib_only(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    log = _log(project, "m-a")
    _append(project, "m-a", "2026-10-23T05:00:01Z", "alpha")
    source = SCRIPT.read_text(encoding="utf-8")
    assert "import iterthink" not in source
    assert "from iterthink" not in source
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONPATH"] = ""
    done = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), str(log)],
        check=False,
        capture_output=True,
        env=env,
        cwd=tmp_path,
    )
    assert done.returncode == 0
    assert main(["verify_log.py", str(log)]) == 0
    assert main(["verify_log.py"]) == 2
