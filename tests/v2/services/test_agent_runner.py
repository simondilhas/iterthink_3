"""The pool, budgets and Claude claims."""

from __future__ import annotations

from pathlib import Path

import pytest

from iterthink.services.bridge import Conflict
from iterthink.services.claims import holder
from iterthink.services.projects import write_yaml
from iterthink.services.task_store import path_of

from .task_support import bridge_for, task_meta, task_text


def test_minutes_over_budget_asks_for_input(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    made = bridge.task_create(project, "Check doors", "Compare.", "user:ada")
    bridge.task_configure(project, made.id, "user:ada", budget=(100, 1))
    bridge.task_ready(project, made.id, "user:ada")
    bridge.task_note_usage(project, made.id, 0, 2)
    assert task_meta(project_dir, made.id)["status"] == "needs-input"


def test_cursor_without_a_key_does_not_launch(tmp_path: Path, project_dir: Path) -> None:
    from .test_cursor_runner import FakeCursor

    bridge, project = bridge_for(tmp_path, project_dir)
    fake = FakeCursor()
    bridge.use_cursor(fake)
    bridge.use_cursor_key("")
    bridge.set_egress(project, "allowed", "user:ada")
    bridge.task_set_remote(project, "https://example.com/doors.git")
    made = bridge.task_create(project, "Check doors", "Compare.", "user:ada")
    bridge.task_configure(project, made.id, "user:ada", agent="cursor-coder")
    bridge.task_ready(project, made.id, "user:ada")
    assert fake.created == []
    assert "cursor key missing" in task_text(project_dir, made.id)


def test_budget_moves_task_to_needs_input(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    made = bridge.task_create(project, "Check doors", "Compare.", "user:ada")
    bridge.task_configure(project, made.id, "user:ada", budget=(3, 20))
    bridge.task_ready(project, made.id, "user:ada")
    bridge.task_note_usage(project, made.id, 2, 0)
    assert task_meta(project_dir, made.id)["status"] == "running"
    bridge.task_note_usage(project, made.id, 2, 0)
    assert task_meta(project_dir, made.id)["status"] == "needs-input"
    assert task_meta(project_dir, made.id)["blocked"] == "budget reached"
    assert "budget reached" in task_text(project_dir, made.id)


def test_local_runner_stops_when_egress_denies(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    bridge.set_egress(project, "none", "user:ada")
    made = bridge.task_create(project, "Check doors", "Compare.", "user:ada")
    bridge.task_ready(project, made.id, "user:ada")
    assert task_meta(project_dir, made.id)["status"] == "needs-input"
    assert "egress blocks the agent" in task_text(project_dir, made.id)


def test_claude_profile_is_claimed_over_mcp_and_not_launched(
    tmp_path: Path, project_dir: Path
) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    made = bridge.task_create(project, "Check doors", "Compare.", "user:ada")
    bridge.task_configure(project, made.id, "user:ada", agent="claude-coder")
    ready = bridge.task_ready(project, made.id, "user:ada")
    assert ready.status == "todo"
    assert task_meta(project_dir, made.id)["status"] == "ready"
    assert task_meta(project_dir, made.id)["runner"] == "claude"
    assert holder(project_dir, path_of(made.id)) is None
    claimed = bridge.task_claim(project, made.id, "agent:claude-code", "claude-code")
    assert claimed.status == "running"
    current = holder(project_dir, path_of(made.id))
    assert current is not None
    assert current.user == "claude:claude-code"
    write_yaml(
        project_dir / ".iterthink" / "settings" / "agents.yaml",
        {"claude-coder": {"max_parallel": 1}},
    )
    other = bridge.task_create(project, "Second", "Wait.", "user:ada")
    bridge.task_configure(project, other.id, "user:ada", agent="claude-coder")
    bridge.task_ready(project, other.id, "user:ada")
    with pytest.raises(Conflict, match="parallel"):
        bridge.task_claim(project, other.id, "agent:claude-code", "claude-code")
