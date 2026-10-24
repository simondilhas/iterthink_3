"""Day one on the real bridge: open, edit, propose, review, restore, restart."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError

from iterthink.mcp.server import build
from iterthink.services.bridge_real import RealBridge
from iterthink.web.app import TOKEN_HEADER, create_app

pytestmark = pytest.mark.e2e

TOKEN = "test-token"
DOC = "Pflichtenheft.md"
ORIGINAL = "# Pflichtenheft\n\nDie Türen im EG sind EI30.\n\nFluchtwege 1.2 m.\n"
EI60 = ORIGINAL.replace("EI30", "EI60")
EI90 = ORIGINAL.replace("EI30", "EI90")
_VERSION = re.compile(r'/versions/([0-9a-f]+)\?[^"]*">([^<]*)</a>')


def _bridge(tmp_path: Path) -> RealBridge:
    return RealBridge(state_dir=tmp_path / "state")


def _client(bridge: RealBridge) -> TestClient:
    app = create_app(bridge=bridge, token=TOKEN, actor="user:simon")
    return TestClient(app, headers={TOKEN_HEADER: TOKEN, "accept": "text/html"})


def _text(project: Path) -> str:
    return (project / DOC).read_text(encoding="utf-8")


def _make(client: TestClient, workspace: Path, project: Path) -> str:
    opened = client.post("/open", data={"path": str(workspace)})
    assert opened.status_code == 200
    assert project.name in opened.text
    assert "Make project" in opened.text
    made = client.post("/projects", data={"path": str(project)}, follow_redirects=False)
    assert made.status_code == 303
    return made.headers["location"].rsplit("/", 1)[-1]


def _version_id(html: str, message: str) -> str:
    found = {text: version for version, text in _VERSION.findall(html)}
    assert message in found
    version = found[message]
    assert isinstance(version, str)
    return version


async def _data(server: object, name: str, arguments: dict[str, object]) -> object:
    result = await server.call_tool(name, arguments)  # type: ignore[attr-defined]
    content = result.structured_content
    if isinstance(content, dict) and set(content) == {"result"}:
        return content["result"]
    return content


async def _propose(bridge: RealBridge, project_id: str, text: str, reason: str) -> str:
    app = build(bridge)
    app.client_name = "claude"
    made = await _data(
        app.mcp,
        "propose",
        {"project": project_id, "changes": {DOC: text}, "reason": reason},
    )
    assert isinstance(made, dict)
    proposal_id = made["id"]
    assert isinstance(proposal_id, str)
    return proposal_id


def test_open_make_project_browse_edit_history(
    tmp_path: Path, workspace_dir: Path, project_dir: Path
) -> None:
    client = _client(_bridge(tmp_path))
    project_id = _make(client, workspace_dir, project_dir)
    explorer = client.get(f"/p/{project_id}/explorer")
    assert "Pflichtenheft.md" in explorer.text
    assert "Türliste.csv" in explorer.text
    page = client.get(f"/p/{project_id}/f/{DOC}")
    assert "EI30" in page.text
    saved = client.post(f"/p/{project_id}/f/{DOC}", data={"text": EI60})
    assert saved.status_code == 200
    assert "Saved" in saved.text
    assert _text(project_dir) == EI60
    panel = client.get(f"/p/{project_id}/panel", params={"tab": "history", "path": DOC})
    assert panel.status_code == 200
    assert "edited Pflichtenheft.md" in panel.text
    assert "started tracking" in panel.text
    assert "simon" in panel.text
    version_id = _version_id(panel.text, "edited Pflichtenheft.md")
    version = client.get(f"/p/{project_id}/versions/{version_id}", params={"path": DOC})
    assert version.status_code == 200
    assert "EI30" in version.text
    assert "EI60" in version.text
    assert "Restore" in version.text


async def test_agent_proposes_user_accepts_file_changes_log_intact(
    tmp_path: Path, workspace_dir: Path, project_dir: Path
) -> None:
    bridge = _bridge(tmp_path)
    client = _client(bridge)
    project_id = _make(client, workspace_dir, project_dir)
    proposal_id = await _propose(bridge, project_id, EI90, "doors are EI90")
    assert _text(project_dir) == ORIGINAL
    page = client.post(f"/p/{project_id}/proposals/{proposal_id}/accept", data={"reason": "yes"})
    assert page.status_code == 200
    assert "Accepted" in page.text
    assert "agent claude" in page.text
    assert _text(project_dir) == EI90
    log = client.get(f"/p/{project_id}/log")
    assert "Log intact" in log.text
    assert bridge.verify(project_id).ok


async def test_agent_proposes_user_rejects_file_unchanged(
    tmp_path: Path, workspace_dir: Path, project_dir: Path
) -> None:
    bridge = _bridge(tmp_path)
    client = _client(bridge)
    project_id = _make(client, workspace_dir, project_dir)
    proposal_id = await _propose(bridge, project_id, EI90, "doors are EI90")
    page = client.post(
        f"/p/{project_id}/proposals/{proposal_id}/reject", data={"reason": "not this one"}
    )
    assert page.status_code == 200
    assert "Rejected" in page.text
    assert _text(project_dir) == ORIGINAL
    log = client.get(f"/p/{project_id}/log")
    assert "not this one" in log.text
    assert "Log intact" in log.text


async def test_conflict_shown_in_review_after_user_edit(
    tmp_path: Path, workspace_dir: Path, project_dir: Path
) -> None:
    bridge = _bridge(tmp_path)
    client = _client(bridge)
    project_id = _make(client, workspace_dir, project_dir)
    proposal_id = await _propose(bridge, project_id, EI90, "doors are EI90")
    saved = client.post(f"/p/{project_id}/f/{DOC}", data={"text": EI60})
    assert "Saved" in saved.text
    page = client.post(f"/p/{project_id}/proposals/{proposal_id}/accept", data={"reason": ""})
    assert page.status_code == 200
    assert "This proposal no longer fits the current file" in page.text
    assert "conflict" in page.text
    assert _text(project_dir) == EI60


def test_restore_through_ui(tmp_path: Path, workspace_dir: Path, project_dir: Path) -> None:
    client = _client(_bridge(tmp_path))
    project_id = _make(client, workspace_dir, project_dir)
    client.post(f"/p/{project_id}/f/{DOC}", data={"text": EI60})
    panel = client.get(f"/p/{project_id}/panel", params={"tab": "history", "path": DOC})
    started = _version_id(panel.text, "started tracking")
    restored = client.post(f"/p/{project_id}/restore", data={"path": DOC, "version": started})
    assert restored.status_code == 200
    assert "Restored" in restored.text
    assert _text(project_dir) == ORIGINAL


async def test_restart_keeps_everything(
    tmp_path: Path, workspace_dir: Path, project_dir: Path
) -> None:
    bridge = _bridge(tmp_path)
    client = _client(bridge)
    project_id = _make(client, workspace_dir, project_dir)
    client.post(f"/p/{project_id}/f/{DOC}", data={"text": EI60})
    await _propose(bridge, project_id, EI90, "doors are EI90")
    again = _client(RealBridge(state_dir=tmp_path / "state"))
    home = again.post("/line", data={"q": "open project"})
    assert "P-101 Schulhaus" in home.text
    page = again.get(f"/p/{project_id}/f/{DOC}")
    assert "EI60" in page.text
    proposals = again.get(f"/p/{project_id}/proposals")
    assert "doors are EI90" in proposals.text
    assert "open" in proposals.text
    log = again.get(f"/p/{project_id}/log")
    assert "Log intact" in log.text


async def test_mcp_refuses_content_until_egress_allowed(
    tmp_path: Path, workspace_dir: Path, project_dir: Path
) -> None:
    bridge = _bridge(tmp_path)
    project_id = _make(_client(bridge), workspace_dir, project_dir)
    app = build(bridge)
    files = await _data(app.mcp, "list_files", {"project": project_id})
    assert isinstance(files, list)
    assert any(item["path"] == DOC for item in files)
    secret = "ada@example.com"
    document = project_dir / DOC
    document.write_text(document.read_text(encoding="utf-8") + secret + "\n", encoding="utf-8")
    shielded = await _data(app.mcp, "read_file", {"project": project_id, "path": DOC})
    assert isinstance(shielded, dict)
    assert secret not in str(shielded.get("text"))
    assert "EMAIL" in str(shielded.get("text"))
    bridge.set_egress(project_id, "none", "user:simon")
    with pytest.raises(ToolError, match=r"egress: none"):
        await app.mcp.call_tool("read_file", {"project": project_id, "path": DOC})
    bridge.set_egress(project_id, "allowed", "user:simon")
    content = await _data(app.mcp, "read_file", {"project": project_id, "path": DOC})
    assert isinstance(content, dict)
    assert secret in str(content["text"])


async def test_sources_untouched_except_by_save_accept_restore(
    tmp_path: Path,
    workspace_dir: Path,
    project_dir: Path,
    source_snapshot: object,
) -> None:
    bridge = _bridge(tmp_path)
    client = _client(bridge)
    original = source_snapshot(project_dir)  # type: ignore[operator]
    project_id = _make(client, workspace_dir, project_dir)
    assert source_snapshot(project_dir) == original  # type: ignore[operator]
    first = await _propose(bridge, project_id, EI90, "try EI90")
    assert source_snapshot(project_dir) == original  # type: ignore[operator]
    rejected = client.post(f"/p/{project_id}/proposals/{first}/reject", data={"reason": "not yet"})
    assert rejected.status_code == 200
    assert source_snapshot(project_dir) == original  # type: ignore[operator]
    saved = client.post(f"/p/{project_id}/f/{DOC}", data={"text": EI60})
    assert "Saved" in saved.text
    after_save = source_snapshot(project_dir)  # type: ignore[operator]
    assert after_save[DOC] != original[DOC]
    for path, digest in original.items():
        if path != DOC:
            assert after_save[path] == digest
    second = await _propose(bridge, project_id, EI90, "try again")
    assert source_snapshot(project_dir) == after_save  # type: ignore[operator]
    accepted = client.post(f"/p/{project_id}/proposals/{second}/accept", data={"reason": ""})
    assert "Accepted" in accepted.text
    panel = client.get(f"/p/{project_id}/panel", params={"tab": "history", "path": DOC})
    started = _version_id(panel.text, "started tracking")
    restored = client.post(f"/p/{project_id}/restore", data={"path": DOC, "version": started})
    assert "Restored" in restored.text
    final = source_snapshot(project_dir)  # type: ignore[operator]
    assert final[DOC] == original[DOC]
