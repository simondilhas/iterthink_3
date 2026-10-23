"""Eight MCP tools. They call the bridge and never decide a verdict."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from iterthink.services.bridge import Bridge, BridgeError, ProposalStatus, get_bridge

_EGRESS = (
    "This project keeps its content on this machine (egress: {value}). "
    "Change it in iterthink's settings to allow agents to read files."
)
_PROPOSE = "Create a proposal. The user must accept it in iterthink. Files are not changed."


def plain(value: Any) -> Any:
    """Dataclasses and tuples become JSON-friendly lists and dicts."""
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def _run(action: Callable[[], object]) -> Any:
    try:
        return plain(action())
    except BridgeError as exc:
        raise ToolError(str(exc)) from exc


@dataclass
class App:
    """The server plus the client name used as the proposal actor."""

    mcp: MCPServer
    client_name: str | None = None

    @property
    def actor(self) -> str:
        return f"agent:{self.client_name or 'mcp'}"


def _content_allowed(bridge: Bridge, project: str) -> None:
    matches = [item for item in bridge.projects() if item.id == project]
    if matches and matches[0].egress != "allowed":
        raise ToolError(_EGRESS.format(value=matches[0].egress))


def _handshake_name(ctx: Context) -> str | None:
    """Client name from the MCP initialize request, when this call has one."""
    try:
        params = ctx.session.client_params
    except (ValueError, AttributeError):
        return None
    info = getattr(params, "client_info", None)
    name = getattr(info, "name", None)
    if isinstance(name, str) and name:
        return name
    return None


def _actor(app: App, ctx: Context) -> str:
    name = _handshake_name(ctx)
    if name:
        return f"agent:{name}"
    return app.actor


def build(bridge: Bridge) -> App:
    """Register the eight tools on a new server bound to `bridge`."""
    app = App(MCPServer("iterthink"))

    @app.mcp.tool(description="Projects opened on this machine.")
    def list_projects() -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], _run(bridge.projects))

    @app.mcp.tool(description="Files in the project. iterthink's own data is hidden.")
    def list_files(project: str) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], _run(lambda: bridge.files(project)))

    @app.mcp.tool(description="Versions, newest first. Optionally one file.")
    def history(project: str, path: str | None = None) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], _run(lambda: bridge.history(project, path)))

    @app.mcp.tool(description="Proposals. Default status is open.")
    def list_proposals(project: str, status: str = "open") -> list[dict[str, Any]]:
        kind = cast(ProposalStatus, status)
        return cast(list[dict[str, Any]], _run(lambda: bridge.proposals(project, kind)))

    @app.mcp.tool(description="Read one file. Refused unless egress is allowed.")
    def read_file(project: str, path: str) -> dict[str, Any]:
        _content_allowed(bridge, project)
        return cast(dict[str, Any], _run(lambda: bridge.read(project, path)))

    @app.mcp.tool(description="Keyword search. Refused unless egress is allowed.")
    def search(project: str, query: str) -> list[dict[str, Any]]:
        _content_allowed(bridge, project)
        return cast(list[dict[str, Any]], _run(lambda: bridge.search(project, query)))

    @app.mcp.tool(description="Diff two states of a file. Refused unless egress is allowed.")
    def diff(
        project: str, path: str, base: str | None = None, target: str | None = None
    ) -> dict[str, Any]:
        _content_allowed(bridge, project)
        return cast(dict[str, Any], _run(lambda: bridge.diff(project, path, base, target)))

    @app.mcp.tool(description=_PROPOSE)
    def propose(
        project: str,
        changes: dict[str, str],
        reason: str,
        ctx: Context,
        baseline: str | None = None,
    ) -> dict[str, Any]:
        actor = _actor(app, ctx)
        made = _run(lambda: bridge.propose(project, changes, actor, reason, baseline))
        return cast(dict[str, Any], made)

    return app


def open_configured(bridge: Bridge) -> None:
    """Open every folder in ITERTHINK_PROJECTS."""
    raw = os.environ.get("ITERTHINK_PROJECTS", "")
    for part in raw.split(os.pathsep):
        if part:
            bridge.open_folder(Path(part))


def main() -> None:
    """Serve over stdio."""
    bridge = get_bridge()
    open_configured(bridge)
    build(bridge).mcp.run("stdio")
