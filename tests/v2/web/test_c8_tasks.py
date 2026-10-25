"""The board: handover, an answer, and overlapping scope."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from iterthink.services.bridge_real import RealBridge
from iterthink.services.task_store import path_of
from iterthink.web.app import TOKEN_HEADER, create_app


def _bridge(tmp_path: Path, project_dir: Path) -> tuple[RealBridge, str]:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    return bridge, bridge.make_project(project_dir).id


def test_board_ready_answer_and_overlap(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    first = bridge.task_create(project, "Check doors", "Compare the ratings.", "user:ada")
    second = bridge.task_create(project, "Check walls", "Compare walls.", "user:ada")
    bridge.task_configure(project, first.id, "user:ada", scope=("specs/**",))
    bridge.task_configure(project, second.id, "user:ada", scope=("specs/fire.md",))
    client = TestClient(create_app(bridge=bridge, token="token", actor="user:ada"))
    headers = {TOKEN_HEADER: "token"}
    page = client.get(f"/p/{project}/tasks", headers=headers)
    assert page.status_code == 200
    assert "Check doors" in page.text
    assert "Overlaps" in page.text
    assert f'id="ready-{first.id}"' in page.text
    ready = client.post(f"/p/{project}/tasks/{first.id}/ready", headers=headers)
    assert ready.status_code == 200
    assert "Running" in ready.text
    bridge.task_ask(project, first.id, "Which rating?", "agent:spec-checker")
    asked = client.get(f"/p/{project}/tasks", headers=headers)
    assert "Which rating?" in asked.text
    answered = client.post(
        f"/p/{project}/tasks/{first.id}/answer", data={"text": "EI30"}, headers=headers
    )
    assert answered.status_code == 200
    text = (project_dir / path_of(first.id)).read_text(encoding="utf-8")
    assert "EI30" in text
    script = Path("iterthink/web/static/js/task-board.js").read_text(encoding="utf-8")
    assert "ready-" in script
    assert "data-column" in script
    bridge.task_complete(project, second.id, "Walls checked.", "agent:spec-checker")
    accepted = client.post(f"/p/{project}/tasks/{second.id}/accept", headers=headers)
    assert accepted.status_code == 200
    events = client.get(f"/p/{project}/tasks/{first.id}/events", headers=headers)
    assert events.status_code == 200
    assert "event: progress" in events.text
    missing = client.get(f"/p/{project}/tasks/t-missing/events", headers=headers)
    assert missing.text.endswith("data: \n\n") or "data:" in missing.text
    hx = {"HX-Request": "true", **headers}
    again = client.post(f"/p/{project}/tasks/{second.id}/again", headers=hx)
    assert again.status_code == 200
    denied = client.post(
        f"/p/{project}/tasks/{first.id}/reject", data={"text": ""}, headers=headers
    )
    assert denied.status_code == 422
