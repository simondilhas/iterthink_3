"""Cursor cloud agent launches. HTTP is faked; one test drives the real client shape."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from iterthink.ai.cursor_agent import CursorError, HttpxCursor
from iterthink.services.bridge import ProposalInfo
from iterthink.services.bridge_real import RealBridge
from iterthink.services.event_log import read_all
from iterthink.services.projects import write_yaml

from .task_support import bridge_for, task_meta, task_text

_REMOTE = "https://example.com/doors.git"
_KEY = "super-secret-key"


class FakeCursor:
    """Records Cloud Agents calls and never opens a socket."""

    def __init__(self) -> None:
        self.created: list[str] = []
        self.loaded: list[str] = []
        self.prompts: list[str] = []
        self.remotes: list[str] = []
        self.models: list[str] = []
        self.auto: list[bool] = []
        self.followed: list[str] = []
        self.cancelled: list[tuple[str, str]] = []
        self.streams: list[dict[str, str]] = []
        self.fail_stream = False
        self.on_cancel: list[Path] = []

    def create_agent(
        self, agent_id: str, prompt: str, remote: str, model: str, key: str, *, auto_pr: bool
    ) -> dict[str, str]:
        del key
        self.created.append(agent_id)
        self.prompts.append(prompt)
        self.remotes.append(remote)
        self.models.append(model)
        self.auto.append(auto_pr)
        if self.created.count(agent_id) > 1:
            return {"error": "already exists", "id": agent_id, "run_id": "", "url": ""}
        return {"id": agent_id, "run_id": "run-1", "url": f"https://cursor.com/agents/{agent_id}"}

    def load_agent(self, agent_id: str, key: str) -> dict[str, str]:
        del key
        self.loaded.append(agent_id)
        return {"id": agent_id, "run_id": "run-2", "url": f"https://cursor.com/agents/{agent_id}"}

    def stream(self, agent_id: str, run_id: str, key: str) -> list[dict[str, str]]:
        del agent_id, run_id, key
        if self.fail_stream:
            raise CursorError("expired")
        return list(self.streams)

    def get_run(self, agent_id: str, run_id: str, key: str) -> dict[str, str]:
        del key
        return {
            "id": agent_id,
            "run_id": run_id,
            "status": "FINISHED",
            "text": "Finished",
            "url": "",
        }

    def follow_up(self, agent_id: str, prompt: str, key: str) -> dict[str, str]:
        del agent_id, key
        self.followed.append(prompt)
        return {"id": "", "run_id": "run-3", "url": "", "status": "", "text": ""}

    def cancel(self, agent_id: str, run_id: str, key: str) -> None:
        del key
        for path in self.on_cancel:
            assert "budget reached" not in path.read_text(encoding="utf-8")
        self.cancelled.append((agent_id, run_id))


def _arm(
    bridge: RealBridge,
    project: str,
    fake: FakeCursor,
    *,
    remote: str = _REMOTE,
    egress: str = "allowed",
) -> str:
    bridge.use_cursor(fake)
    bridge.use_cursor_key(_KEY)
    bridge.set_egress(project, egress, "user:ada")
    if remote:
        bridge.task_set_remote(project, remote)
    made = bridge.task_create(project, "Check doors", "List mismatches.", "user:ada")
    bridge.task_configure(
        project, made.id, "user:ada", agent="cursor-coder", scope=("Pflichtenheft.md",)
    )
    return made.id


def test_cursor_profile_launches_on_handover_and_stores_ids(
    tmp_path: Path, project_dir: Path
) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    fake = FakeCursor()
    task_id = _arm(bridge, project, fake)
    started = bridge.task_ready(project, task_id, "user:ada")
    assert started.status == "running"
    cursor = task_meta(project_dir, task_id)["cursor"]
    assert isinstance(cursor, dict)
    assert cursor["agent_id"] == fake.created[0]
    assert cursor["run_id"] == "run-1"
    assert str(cursor["url"]).startswith("https://cursor.com/agents/")
    assert fake.auto == [False]
    assert fake.remotes == [_REMOTE]
    assert "Check doors" in fake.prompts[0]
    assert "List mismatches" in fake.prompts[0]
    assert _KEY not in task_text(project_dir, task_id)
    folder = project_dir / ".iterthink" / "log"
    log = "\n".join(path.read_text(encoding="utf-8") for path in folder.glob("*.jsonl"))
    assert _KEY not in log
    launched = [event for event in read_all(project_dir) if event.type == "task_launched"]
    assert launched[-1].payload["agent_id"] == fake.created[0]
    assert launched[-1].payload["run_id"] == "run-1"


def test_cursor_retry_reuses_the_stored_agent_id(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    fake = FakeCursor()
    task_id = _arm(bridge, project, fake)
    bridge.task_ready(project, task_id, "user:ada")
    bridge.task_run_again(project, task_id, "user:ada")
    assert fake.created[0] == fake.created[1]
    assert fake.loaded == [fake.created[0]]
    cursor = task_meta(project_dir, task_id)["cursor"]
    assert isinstance(cursor, dict)
    assert cursor["agent_id"] == fake.created[0]


def test_cursor_stream_event_updates_card_progress(tmp_path: Path, project_dir: Path) -> None:
    from fastapi.testclient import TestClient

    from iterthink.web.app import TOKEN_HEADER, create_app

    bridge, project = bridge_for(tmp_path, project_dir)
    fake = FakeCursor()
    task_id = _arm(bridge, project, fake)
    bridge.task_ready(project, task_id, "user:ada")
    fake.streams = [{"type": "tool_call", "text": "Reading the spec", "status": "RUNNING"}]
    bridge.task_apply_stream(project, task_id)
    assert task_meta(project_dir, task_id)["progress"] == "Reading the spec"
    client = TestClient(create_app(bridge=bridge, token="token", actor="user:ada"))
    page = client.get(f"/p/{project}/tasks", headers={TOKEN_HEADER: "token"})
    assert "Reading the spec" in page.text


def test_cursor_finished_moves_to_review_with_open_agent_link(
    tmp_path: Path, project_dir: Path
) -> None:
    from fastapi.testclient import TestClient

    from iterthink.web.app import TOKEN_HEADER, create_app

    bridge, project = bridge_for(tmp_path, project_dir)
    fake = FakeCursor()
    task_id = _arm(bridge, project, fake)
    bridge.task_ready(project, task_id, "user:ada")
    fake.streams = [{"type": "status", "text": "", "status": "FINISHED"}]
    bridge.task_apply_stream(project, task_id)
    assert task_meta(project_dir, task_id)["status"] == "review"
    client = TestClient(create_app(bridge=bridge, token="token", actor="user:ada"))
    page = client.get(f"/p/{project}/tasks", headers={TOKEN_HEADER: "token"})
    assert "Open agent" in page.text
    assert f"https://cursor.com/agents/{fake.created[0]}" in page.text


def test_cursor_answer_posts_a_follow_up_run(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    fake = FakeCursor()
    task_id = _arm(bridge, project, fake)
    bridge.task_ready(project, task_id, "user:ada")
    bridge.task_ask(project, task_id, "Which rating?", "agent:cursor-coder")
    bridge.task_answer(project, task_id, "Use EI30", "user:ada")
    assert "Use EI30" in task_text(project_dir, task_id)
    assert fake.followed == ["Use EI30"]


def test_cursor_cancel_cancels_the_run(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    fake = FakeCursor()
    task_id = _arm(bridge, project, fake)
    bridge.task_ready(project, task_id, "user:ada")
    proposal = bridge.task_propose(
        project, task_id, {"Pflichtenheft.md": "draft\n"}, "agent:cursor-coder", "draft"
    )
    bridge.task_cancel(project, task_id, "user:ada")
    assert fake.cancelled == [(fake.created[0], "run-1")]
    assert task_meta(project_dir, task_id)["status"] == "cancelled"
    open_ones = bridge.proposals(project, None)
    still: ProposalInfo = next(item for item in open_ones if item.id == proposal.id)
    assert still.status == "open"


def test_cursor_blocked_when_egress_is_not_allowed_or_remote_missing(
    tmp_path: Path, project_dir: Path
) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    fake = FakeCursor()
    shielded = _arm(bridge, project, fake, egress="shielded")
    bridge.task_ready(project, shielded, "user:ada")
    assert task_meta(project_dir, shielded)["status"] == "needs-input"
    assert "egress must be allowed" in task_text(project_dir, shielded)
    assert fake.created == []
    bridge.set_egress(project, "allowed", "user:ada")
    bridge.task_set_remote(project, "")
    missing = bridge.task_create(project, "No remote", "Wait.", "user:ada")
    bridge.task_configure(project, missing.id, "user:ada", agent="cursor-coder")
    bridge.task_ready(project, missing.id, "user:ada")
    assert task_meta(project_dir, missing.id)["status"] == "needs-input"
    assert "no remote" in task_text(project_dir, missing.id)
    assert fake.created == []


def test_cursor_budget_cancels_before_needs_input(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    fake = FakeCursor()
    task_id = _arm(bridge, project, fake)
    bridge.task_configure(project, task_id, "user:ada", budget=(4, 20))
    bridge.task_ready(project, task_id, "user:ada")
    fake.on_cancel = [project_dir / ".iterthink" / "tasks" / f"{task_id}.md"]
    bridge.task_note_usage(project, task_id, 5, 0)
    assert fake.cancelled
    assert task_meta(project_dir, task_id)["status"] == "needs-input"
    assert "budget reached" in task_text(project_dir, task_id)


def test_claude_model_on_a_cursor_profile_stays_runner_cursor(
    tmp_path: Path, project_dir: Path
) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    write_yaml(
        project_dir / ".iterthink" / "settings" / "agents.yaml",
        {"cursor-coder": {"cursor_model": "claude-3-5-sonnet"}},
    )
    fake = FakeCursor()
    task_id = _arm(bridge, project, fake)
    bridge.task_ready(project, task_id, "user:ada")
    assert task_meta(project_dir, task_id)["runner"] == "cursor"
    assert fake.models == ["claude-3-5-sonnet"]


def test_cursor_stream_falls_back_to_the_run(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = bridge_for(tmp_path, project_dir)
    fake = FakeCursor()
    task_id = _arm(bridge, project, fake)
    bridge.task_ready(project, task_id, "user:ada")
    fake.fail_stream = True
    bridge.task_apply_stream(project, task_id)
    assert task_meta(project_dir, task_id)["status"] == "review"
    assert task_meta(project_dir, task_id)["progress"] == "Finished"


def test_http_client_posts_the_v1_shape() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("/stream"):
            body = 'data: {"type": "tool_call", "text": "Reading"}\n'
            return httpx.Response(200, text=body)
        if request.method == "GET":
            return httpx.Response(
                200, json={"id": "agent-1", "runId": "run-9", "url": "https://cursor.com/a"}
            )
        return httpx.Response(
            200,
            json={"id": "agent-1", "run_id": "run-1", "url": "https://cursor.com/agents/agent-1"},
        )

    client = HttpxCursor(transport=httpx.MockTransport(handler))
    created = client.create_agent("agent-1", "Check", _REMOTE, "claude-3", "key", auto_pr=False)
    assert created["run_id"] == "run-1"
    sent = json.loads(seen[0].content)
    assert sent["autoCreatePR"] is False
    assert sent["prompt"]["text"] == "Check"
    assert sent["cursor_model"] == "claude-3"
    assert client.load_agent("agent-1", "key")["run_id"] == "run-9"
    assert client.stream("agent-1", "run-1", "key")[0]["text"] == "Reading"
    client.follow_up("agent-1", "EI30", "key")
    client.cancel("agent-1", "run-1", "key")
    assert seen[-1].url.path.endswith("/cancel")


def test_http_client_reports_a_bad_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/stream"):
            body = 'event: ping\ndata: [not json]\ndata: {"text": "ok"}\n'
            return httpx.Response(200, text=body)
        if path.endswith("/runs/run-1"):
            return httpx.Response(200, json=["nope"])
        return httpx.Response(500, text="nope")

    client = HttpxCursor(transport=httpx.MockTransport(handler))
    with pytest.raises(CursorError):
        client.follow_up("agent-1", "hi", "key")
    assert client.stream("agent-1", "run-1", "key") == [{"text": "ok"}]
    assert client.get_run("agent-1", "run-1", "key")["id"] == "agent-1"


def test_http_client_reads_a_json_event_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, text='[{"text": "a"}, "x"]')

    client = HttpxCursor(transport=httpx.MockTransport(handler))
    assert client.stream("agent-1", "run-1", "key") == [{"text": "a"}]


def test_http_client_treats_already_exists_as_a_load() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(409, json={"error": "already exists"})

    client = HttpxCursor(transport=httpx.MockTransport(handler))
    created = client.create_agent("agent-1", "Check", _REMOTE, "", "key", auto_pr=False)
    assert created["error"] == "already exists"
