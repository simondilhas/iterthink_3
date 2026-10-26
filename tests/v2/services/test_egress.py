"""Project egress: deny, shield, or send, and record the decision."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError

from iterthink import config
from iterthink.mcp.server import build
from iterthink.privacy_shield_settings import load_categories
from iterthink.services.bridge_real import RealBridge
from iterthink.services.egress import EgressDenied, check, deliver, prepare, restore
from iterthink.services.event_log import read_all
from iterthink.services.projects import project_file, settings_of, write_yaml
from iterthink.web.app import TOKEN_HEADER, create_app

SECRET = "ada@example.com"
_PURPOSES = ("agent", "app_build", "app_ai", "chat", "impact", "mcp")
_TIERS = ("company", "cloud")


@pytest.fixture(autouse=True)
def _shield_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "STORE_DIR", tmp_path / "shield")
    load_categories(reload=True)


def _bridge(tmp_path: Path) -> RealBridge:
    return RealBridge(state_dir=tmp_path / "state", machine="m-test")


def _root(tmp_path: Path, project_dir: Path) -> tuple[RealBridge, str, Path]:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    return bridge, project, project_dir


def _set(root: Path, mode: str) -> None:
    data = settings_of(root)
    data["egress"] = mode
    write_yaml(project_file(root), data)


async def _data(server: object, name: str, arguments: dict[str, object]) -> object:
    result = await server.call_tool(name, arguments)  # type: ignore[attr-defined]
    content = result.structured_content
    if isinstance(content, dict) and set(content) == {"result"}:
        return content["result"]
    return content


@pytest.mark.parametrize("purpose", _PURPOSES)
@pytest.mark.parametrize("tier", _TIERS)
def test_none_blocks_company_and_cloud_for_every_purpose(
    tmp_path: Path, project_dir: Path, purpose: str, tier: str
) -> None:
    _root(tmp_path, project_dir)
    _set(project_dir, "none")
    assert check(project_dir, purpose, tier) == "deny"  # type: ignore[arg-type]
    sent: list[str] = []

    def send(text: str) -> str:
        sent.append(text)
        return text

    with pytest.raises(EgressDenied):
        deliver(project_dir, purpose, tier, "hello", send)
    assert sent == []


def test_app_build_schemas_are_shielded_when_egress_is_shielded(
    tmp_path: Path, project_dir: Path
) -> None:
    _root(tmp_path, project_dir)
    schema = f"owner email {SECRET}"
    shielded = prepare(project_dir, schema, "app_build", "cloud")
    assert shielded.decision == "shield"
    assert SECRET not in shielded.text
    assert "EMAIL" in shielded.text


def test_shielded_redacts_patterns_and_leaves_names(tmp_path: Path, project_dir: Path) -> None:
    _root(tmp_path, project_dir)
    text = "Isolde Brennan, Bahnhofstrasse 12, writes ada@example.com"
    shielded = prepare(project_dir, text, "mcp", "cloud")
    assert "ada@example.com" not in shielded.text
    assert "EMAIL" in shielded.text
    assert "Isolde Brennan" in shielded.text
    assert "Bahnhofstrasse" in shielded.text


def test_shielded_redacts_and_restores_placeholders(tmp_path: Path, project_dir: Path) -> None:
    _root(tmp_path, project_dir)
    text = f"Write to {SECRET} please"
    shielded = prepare(project_dir, text, "chat", "company")
    assert SECRET not in shielded.text
    assert "{{EMAIL_1}}" in shielded.text
    assert restore(shielded, f"Sent to {shielded.text}") == f"Sent to {text}"
    events = [event for event in read_all(project_dir) if event.type == "egress"]
    assert events[-1].payload["purpose"] == "chat"
    assert events[-1].payload["tier"] == "company"
    assert SECRET not in str(events[-1].payload)


def test_allowed_passes_text_unchanged(tmp_path: Path, project_dir: Path) -> None:
    _root(tmp_path, project_dir)
    _set(project_dir, "allowed")
    text = f"{SECRET} stays"
    shielded = prepare(project_dir, text, "chat", "cloud")
    assert shielded.text == text
    assert shielded.placeholders == {}
    assert not any(event.type == "egress" for event in read_all(project_dir))


def test_egress_changes_are_logged(tmp_path: Path, project_dir: Path) -> None:
    bridge, project, root = _root(tmp_path, project_dir)
    bridge.set_egress(project, "none", "user:ada")
    events = [event for event in read_all(root) if event.type == "settings"]
    assert events[-1].payload["old"] == "shielded"
    assert events[-1].payload["new"] == "none"
    assert events[-1].actor == "user:ada"


def test_settings_page_switches_egress(tmp_path: Path, project_dir: Path) -> None:
    bridge, project, _root_dir = _root(tmp_path, project_dir)
    app = create_app(bridge=bridge, token="test-token", actor="user:ada")
    client = TestClient(app, headers={TOKEN_HEADER: "test-token", "accept": "text/html"})
    page = client.get(f"/p/{project}/settings")
    assert page.status_code == 200
    assert "shielded" in page.text
    assert "does not remove names" in page.text
    saved = client.post(f"/p/{project}/settings", data={"egress": "none"})
    assert saved.status_code == 200
    assert "Saved." in saved.text
    assert bridge.projects()[0].egress == "none"


async def test_mcp_shielded_returns_redacted_content(tmp_path: Path, project_dir: Path) -> None:
    (project_dir / "note.md").write_text(f"Reach {SECRET}\n", encoding="utf-8")
    bridge, project, _root_dir = _root(tmp_path, project_dir)
    app = build(bridge)
    content = await _data(app.mcp, "read_file", {"project": project, "path": "note.md"})
    assert isinstance(content, dict)
    assert SECRET not in str(content.get("text"))
    assert "EMAIL" in str(content.get("text"))
    bridge.set_egress(project, "none", "user:ada")
    with pytest.raises(ToolError, match="egress: none"):
        await app.mcp.call_tool("read_file", {"project": project, "path": "note.md"})


async def test_mcp_shielded_redacts_paths_messages_and_reasons(
    tmp_path: Path, project_dir: Path
) -> None:
    name = f"{SECRET}.md"
    (project_dir / name).write_text("plain\n", encoding="utf-8")
    bridge, project, _root_dir = _root(tmp_path, project_dir)
    bridge.save(project, name, "plain\nmore\n", "user:ada", f"note for {SECRET}")
    bridge.propose(project, {name: "next\n"}, "user:ada", f"because {SECRET}")
    app = build(bridge)
    files = await _data(app.mcp, "list_files", {"project": project})
    versions = await _data(app.mcp, "history", {"project": project})
    proposals = await _data(app.mcp, "list_proposals", {"project": project})
    read = await _data(app.mcp, "read_file", {"project": project, "path": name})
    leaked = str((files, versions, proposals, read))
    assert SECRET not in leaked
    assert "EMAIL" in leaked


@pytest.mark.parametrize("tool", ["list_files", "history", "list_proposals"])
async def test_mcp_metadata_refused_when_egress_is_none(
    tmp_path: Path, project_dir: Path, tool: str
) -> None:
    bridge, project, _root_dir = _root(tmp_path, project_dir)
    bridge.set_egress(project, "none", "user:ada")
    app = build(bridge)
    with pytest.raises(ToolError, match="egress: none"):
        await app.mcp.call_tool(tool, {"project": project})
