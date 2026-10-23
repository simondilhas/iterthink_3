"""MCP tools over the fake bridge. No subprocess except the stdio smoke test."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import Implementation

from iterthink.mcp.server import build
from iterthink.services.bridge_fake import FakeBridge

_CONTENT = ("read_file", "search", "diff")
_TOOLS = {
    "list_projects",
    "list_files",
    "history",
    "list_proposals",
    "read_file",
    "search",
    "diff",
    "propose",
}
_EGRESS = (
    "This project keeps its content on this machine (egress: {value}). "
    "Change it in iterthink's settings to allow agents to read files."
)


@pytest.fixture
def bridge() -> FakeBridge:
    return FakeBridge()


@pytest.fixture
def project_id(bridge: FakeBridge, project_dir: Path) -> str:
    return bridge.make_project(project_dir).id


async def _data(server: object, name: str, arguments: dict[str, object]) -> object:
    result = await server.call_tool(name, arguments)  # type: ignore[attr-defined]
    content = result.structured_content
    if isinstance(content, dict) and set(content) == {"result"}:
        return content["result"]
    return content


async def test_tool_list_is_exactly_the_eight_tools(bridge: FakeBridge) -> None:
    app = build(bridge)
    tools = await app.mcp.list_tools()
    names = {tool.name for tool in tools}
    assert names == _TOOLS
    assert names.isdisjoint({"accept", "reject", "save", "restore"})


async def test_list_projects_and_files(bridge: FakeBridge, project_id: str) -> None:
    app = build(bridge)
    projects = await _data(app.mcp, "list_projects", {})
    assert isinstance(projects, list)
    assert projects[0]["id"] == project_id
    files = await _data(app.mcp, "list_files", {"project": project_id})
    assert isinstance(files, list)
    assert any(item["path"] == "Pflichtenheft.md" for item in files)


async def test_read_file_allowed_when_egress_allowed(bridge: FakeBridge, project_id: str) -> None:
    bridge.set_egress(project_id, "allowed", "user:simon")
    app = build(bridge)
    content = await _data(app.mcp, "read_file", {"project": project_id, "path": "Pflichtenheft.md"})
    assert isinstance(content, dict)
    assert "EI30" in str(content["text"])


@pytest.mark.parametrize("egress", ["shielded", "none"])
@pytest.mark.parametrize("tool", _CONTENT)
async def test_content_tools_refused_when_egress_shielded_or_none(
    bridge: FakeBridge, project_id: str, egress: str, tool: str
) -> None:
    bridge.set_egress(project_id, egress, "user:simon")  # type: ignore[arg-type]
    app = build(bridge)
    arguments: dict[str, object] = {
        "project": project_id,
        "path": "Pflichtenheft.md",
        "query": "EI",
    }
    with pytest.raises(ToolError, match="keeps its content on this machine"):
        await app.mcp.call_tool(tool, arguments)


async def test_metadata_tools_work_under_egress_none(bridge: FakeBridge, project_id: str) -> None:
    bridge.set_egress(project_id, "none", "user:simon")
    app = build(bridge)
    files = await _data(app.mcp, "list_files", {"project": project_id})
    history = await _data(app.mcp, "history", {"project": project_id})
    proposals = await _data(app.mcp, "list_proposals", {"project": project_id})
    assert isinstance(files, list)
    assert files
    assert isinstance(history, list)
    assert history
    assert proposals == []


async def test_propose_creates_open_proposal_and_leaves_files(
    bridge: FakeBridge,
    project_id: str,
    project_dir: Path,
    source_snapshot: object,
) -> None:
    before = source_snapshot(project_dir)  # type: ignore[operator]
    app = build(bridge)
    await _data(
        app.mcp,
        "propose",
        {
            "project": project_id,
            "changes": {"Pflichtenheft.md": "Neu\n"},
            "reason": "retitle",
        },
    )
    assert source_snapshot(project_dir) == before  # type: ignore[operator]
    proposals = bridge.proposals(project_id)
    assert proposals[0].status == "open"
    assert proposals[0].reason == "retitle"
    assert "Neu" not in (project_dir / "Pflichtenheft.md").read_text(encoding="utf-8")


async def test_actor_comes_from_client_name(bridge: FakeBridge, project_id: str) -> None:
    app = build(bridge)
    app.client_name = "claude"
    await app.mcp.call_tool(
        "propose",
        {
            "project": project_id,
            "changes": {"Pflichtenheft.md": "Neu\n"},
            "reason": "retitle",
        },
    )
    assert bridge.proposals(project_id)[0].actor == "agent:claude"


async def test_propose_of_hidden_config_is_refused(
    bridge: FakeBridge, project_id: str, project_dir: Path
) -> None:
    app = build(bridge)
    with pytest.raises(ToolError, match="hidden"):
        await app.mcp.call_tool(
            "propose",
            {
                "project": project_id,
                "changes": {".cursor/mcp.json": "{}"},
                "reason": "add a server",
            },
        )
    assert bridge.proposals(project_id, None) == []
    assert not (project_dir / ".cursor").exists()


async def test_bridge_error_becomes_tool_error(bridge: FakeBridge, project_id: str) -> None:
    bridge.set_egress(project_id, "allowed", "user:simon")
    app = build(bridge)
    with pytest.raises(ToolError, match="no file"):
        await app.mcp.call_tool("read_file", {"project": project_id, "path": "missing.md"})


@pytest.mark.integration
async def test_server_starts_over_stdio() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "iterthink.mcp"],
        env={"ITERTHINK_BRIDGE": "fake"},
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        listed = await session.list_tools()
    names = {tool.name for tool in listed.tools}
    assert names == _TOOLS


@pytest.mark.integration
async def test_stdio_propose_uses_initialize_client_name(tmp_path: Path) -> None:
    project = tmp_path / "Notes"
    project.mkdir()
    (project / "note.md").write_text("Hello\n", encoding="utf-8")
    info = FakeBridge().make_project(project)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "iterthink.mcp"],
        env={"ITERTHINK_BRIDGE": "fake", "ITERTHINK_PROJECTS": str(project)},
    )
    client = Implementation(name="claude", version="1")
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write, client_info=client) as session,
    ):
        await session.initialize()
        result = await session.call_tool(
            "propose",
            {
                "project": info.id,
                "changes": {"note.md": "Neu\n"},
                "reason": "retitle",
            },
        )
    assert result.structured_content is not None
    assert result.structured_content["actor"] == "agent:claude"
    assert "Neu" not in (project / "note.md").read_text(encoding="utf-8")
