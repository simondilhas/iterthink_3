"""Task files, handover, proposals and the MCP task tools."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from iterthink.mcp.server import build
from iterthink.services.bridge import Conflict, Forbidden
from iterthink.services.bridge_fake import FakeBridge
from iterthink.services.event_log import read_all

from .task_support import bridge_for, task_meta, task_text, version_statuses

_KEYS = (
    "id",
    "title",
    "status",
    "agent",
    "runner",
    "inputs",
    "scope",
    "depends_on",
    "budget",
    "created_by",
)


def test_task_file_front_matter_and_each_status_change_is_a_version(
    tmp_path: Path, project_dir: Path
) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    made = bridge.task_create(project, "Check doors", "Compare the ratings.", "user:ada")
    meta = task_meta(project_dir, made.id)
    for key in _KEYS:
        assert key in meta
    assert meta["status"] == "backlog"
    assert meta["agent"] == "spec-checker"
    assert meta["runner"] == "local"
    budget = meta["budget"]
    assert isinstance(budget, dict)
    assert budget["tokens"] == 200000
    assert budget["minutes"] == 20
    assert "Compare the ratings." in task_text(project_dir, made.id)
    bridge.task_ready(project, made.id, "user:ada")
    bridge.task_ask(project, made.id, "Which rating?", "agent:spec-checker")
    bridge.task_complete(project, made.id, "Listed them.", "agent:spec-checker")
    bridge.task_accept_delivery(project, made.id, "user:ada")
    assert version_statuses(project_dir, made.id) == [
        "backlog",
        "ready",
        "running",
        "needs-input",
        "review",
        "done",
    ]


def test_only_user_moves_backlog_to_ready(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    made = bridge.task_create(project, "Check doors", "Compare.", "user:ada")
    with pytest.raises(Forbidden):
        bridge.task_ready(project, made.id, "agent:spec-checker")
    with pytest.raises(Forbidden):
        bridge.task_start(project, made.id, "agent:spec-checker")
    assert task_meta(project_dir, made.id)["status"] == "backlog"
    bridge.task_ready(project, made.id, "user:ada")
    assert "ready" in version_statuses(project_dir, made.id)


def test_dependency_blocks_start(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    first = bridge.task_create(project, "Read the spec", "Read it.", "user:ada")
    second = bridge.task_create(project, "Check doors", "Compare.", "user:ada", (first.id,))
    bridge.task_ready(project, second.id, "user:ada")
    assert task_meta(project_dir, second.id)["status"] == "ready"
    with pytest.raises(Conflict, match="depend"):
        bridge.task_start(project, second.id, "user:ada")
    bridge.task_ready(project, first.id, "user:ada")
    bridge.task_complete(project, first.id, "Read.", "agent:spec-checker")
    bridge.task_accept_delivery(project, first.id, "user:ada")
    started = bridge.task_start(project, second.id, "user:ada")
    assert started.status == "running"
    assert task_meta(project_dir, second.id)["status"] == "running"


def test_task_info_reports_the_spec_status_of_the_file(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    made = bridge.task_create(project, "Check doors", "Compare.", "user:ada")
    seen = [made.status]
    seen.append(bridge.task_ready(project, made.id, "user:ada").status)
    seen.append(bridge.task_ask(project, made.id, "Which floor?", "agent:spec-checker").status)
    seen.append(bridge.task_cancel(project, made.id, "user:ada").status)
    assert seen == ["backlog", "running", "needs-input", "cancelled"]
    assert bridge.tasks(project)[0].status == task_meta(project_dir, made.id)["status"]


def test_claimed_task_not_started_twice(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    made = bridge.task_create(project, "Check doors", "Compare.", "user:ada")
    assert bridge.task_ready(project, made.id, "user:ada").status == "running"
    with pytest.raises(Conflict):
        bridge.task_start(project, made.id, "user:ada")


def test_agent_limited_to_profile_blocks_and_scope(tmp_path: Path, project_dir: Path) -> None:
    (project_dir / "specs").mkdir()
    (project_dir / "specs" / "note.md").write_text("old\n", encoding="utf-8")
    (project_dir / "secret.md").write_text("secret\n", encoding="utf-8")
    bridge, project = bridge_for(tmp_path, project_dir)
    made = bridge.task_create(project, "Check doors", "Compare.", "user:ada")
    bridge.task_configure(project, made.id, "user:ada", scope=("specs/**",))
    with pytest.raises(Forbidden, match="cannot deliver"):
        bridge.task_call(project, made.id, "deliver", "agent:spec-checker")
    with pytest.raises(Forbidden, match="outside"):
        bridge.task_propose(project, made.id, {"secret.md": "no\n"}, "agent:spec-checker", "no")
    proposal = bridge.task_propose(
        project, made.id, {"specs/note.md": "new\n"}, "agent:spec-checker", "fix the note"
    )
    assert (project_dir / "secret.md").read_text(encoding="utf-8") == "secret\n"
    assert (project_dir / "specs" / "note.md").read_text(encoding="utf-8") == "old\n"
    again = next(item for item in bridge.tasks(project) if item.id == made.id)
    assert proposal.id in again.proposals


def test_ask_and_answer_appends_to_task_file(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    made = bridge.task_create(project, "Check doors", "Compare the ratings.", "user:ada")
    bridge.task_ask(project, made.id, "Which rating?", "agent:spec-checker")
    assert task_meta(project_dir, made.id)["status"] == "needs-input"
    assert "Which rating?" in task_text(project_dir, made.id)
    bridge.task_answer(project, made.id, "EI30", "user:ada")
    text = task_text(project_dir, made.id)
    assert "## Answer" in text
    assert "EI30" in text
    assert "Which rating?" in text


def test_task_outputs_are_proposals_linked_to_task(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    made = bridge.task_create(project, "Check doors", "Compare.", "user:ada")
    bridge.task_configure(project, made.id, "user:ada", scope=("Pflichtenheft.md",))
    proposal = bridge.task_propose(
        project, made.id, {"Pflichtenheft.md": "updated\n"}, "agent:spec-checker", "ratings"
    )
    assert f"(task {made.id})" in proposal.reason
    linked = next(item for item in bridge.tasks(project) if item.id == made.id)
    assert proposal.id in linked.proposals
    found = [
        event
        for event in read_all(project_dir)
        if event.type == "task_proposal" and event.payload.get("task") == made.id
    ]
    assert found[0].payload["proposal"] == proposal.id
    source = (project_dir / "Pflichtenheft.md").read_text(encoding="utf-8")
    assert source.startswith("# Pflichtenheft")


def test_all_accepted_moves_to_done_rejected_moves_to_rejected(
    tmp_path: Path, project_dir: Path
) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    accepted = _with_proposal(bridge, project, "Accept me")
    bridge.task_complete(project, accepted, "Done.", "agent:spec-checker")
    proposal = next(item for item in bridge.tasks(project) if item.id == accepted).proposals[0]
    bridge.accept(project, proposal, "user:ada", "good")
    assert task_meta(project_dir, accepted)["status"] == "done"
    rejected = _with_proposal(bridge, project, "Reject me")
    bridge.task_complete(project, rejected, "Done.", "agent:spec-checker")
    other = next(item for item in bridge.tasks(project) if item.id == rejected).proposals[0]
    bridge.reject(project, other, "user:ada", "wrong rating")
    assert task_meta(project_dir, rejected)["status"] == "rejected"
    assert "wrong rating" in task_text(project_dir, rejected)


def test_competing_proposals_show_in_review_and_run_again(
    tmp_path: Path, project_dir: Path
) -> None:
    from fastapi.testclient import TestClient

    from iterthink.web.app import TOKEN_HEADER, create_app

    bridge, project = bridge_for(tmp_path, project_dir)
    made = bridge.task_create(project, "Check doors", "Compare.", "user:ada")
    bridge.task_configure(project, made.id, "user:ada", scope=("Pflichtenheft.md",))
    first = bridge.task_propose(
        project, made.id, {"Pflichtenheft.md": "one\n"}, "agent:spec-checker", "one"
    )
    second = bridge.task_propose(
        project, made.id, {"Pflichtenheft.md": "two\n"}, "agent:spec-checker", "two"
    )
    bridge.task_complete(project, made.id, "Both filed.", "agent:spec-checker")
    client = TestClient(create_app(bridge=bridge, token="token", actor="user:ada"))
    page = client.get(f"/p/{project}/tasks", headers={TOKEN_HEADER: "token"})
    assert first.id in page.text
    assert second.id in page.text
    bridge.accept(project, first.id, "user:ada", "keep the first")
    conflict = next(item for item in bridge.proposals(project, None) if item.id == second.id)
    assert conflict.status == "conflict"
    again = client.get(f"/p/{project}/tasks", headers={TOKEN_HEADER: "token"})
    assert "Run again on the new version" in again.text
    bridge.task_run_again(project, made.id, "user:ada")
    assert "ready" in version_statuses(project_dir, made.id)


async def test_mcp_task_tools(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    bridge.set_egress(project, "allowed", "user:ada")
    made = bridge.task_create(project, "Check doors", "Compare.", "user:ada")
    bridge.task_configure(project, made.id, "user:ada", agent="claude-coder")
    bridge.task_ready(project, made.id, "user:ada")
    app = build(bridge)
    tools = await app.mcp.list_tools()
    names = {tool.name for tool in tools}
    assert {"list_tasks", "claim_task", "update_task", "ask", "complete_task"} <= names
    listed = await _call(app, "list_tasks", {"project": project})
    assert isinstance(listed, list)
    assert listed[0]["id"] == made.id
    claimed = await _call(
        app, "claim_task", {"project": project, "task_id": made.id, "client": "claude"}
    )
    assert isinstance(claimed, dict)
    assert claimed["status"] == "running"
    await _call(app, "update_task", {"project": project, "task_id": made.id, "progress": "Reading"})
    assert task_meta(project_dir, made.id)["progress"] == "Reading"
    await _call(app, "ask", {"project": project, "task_id": made.id, "question": "Which door?"})
    assert "Which door?" in task_text(project_dir, made.id)
    await _call(
        app, "complete_task", {"project": project, "task_id": made.id, "summary": "No mismatches"}
    )
    assert task_meta(project_dir, made.id)["status"] == "review"


async def test_task_tools_refuse_when_the_bridge_has_none() -> None:
    app = build(FakeBridge())
    with pytest.raises(ToolError, match="list_tasks"):
        await _call(app, "list_tasks", {"project": "missing"})


def _with_proposal(bridge: object, project: str, title: str) -> str:
    from iterthink.services.bridge_real import RealBridge

    real = bridge if isinstance(bridge, RealBridge) else None
    assert real is not None
    made = real.task_create(project, title, "Compare.", "user:ada")
    real.task_configure(project, made.id, "user:ada", scope=("Pflichtenheft.md",))
    real.task_propose(
        project, made.id, {"Pflichtenheft.md": f"{title}\n"}, "agent:spec-checker", title
    )
    return made.id


async def _call(app: object, name: str, arguments: dict[str, object]) -> object:
    result = await app.mcp.call_tool(name, arguments)  # type: ignore[attr-defined]
    content = result.structured_content
    if isinstance(content, dict) and set(content) == {"result"}:
        return content["result"]
    return content
