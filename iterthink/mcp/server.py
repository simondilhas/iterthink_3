"""MCP tools. They call the bridge and never decide a verdict."""

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
_CONTENT = "Redacted when egress is shielded. Refused when it is none."


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


def _mode(bridge: Bridge, project: str) -> str | None:
    matches = [item for item in bridge.projects() if item.id == project]
    if not matches:
        return None
    return matches[0].egress


def _guard(bridge: Bridge, project: str) -> str | None:
    mode = _mode(bridge, project)
    shield = getattr(bridge, "shield_text", None)
    if mode in {None, "allowed"} or (mode == "shielded" and callable(shield)):
        return mode
    raise ToolError(_EGRESS.format(value=mode))


def _redact(shield: object, project: str, value: object) -> object:
    """Redact every string, including paths, kinds and ids."""
    if isinstance(value, str):
        if value == "":
            return value
        return shield(project, value)  # type: ignore[operator]
    if isinstance(value, dict):
        return {str(name): _redact(shield, project, item) for name, item in value.items()}
    if isinstance(value, list):
        return [_redact(shield, project, item) for item in value]
    return value


def _opened(bridge: Bridge, project: str, value: object) -> object:
    """File lists, history and proposals stop at egress none. Shielded redacts them."""
    mode = _mode(bridge, project)
    if mode == "none":
        raise ToolError(_EGRESS.format(value=mode))
    shield = getattr(bridge, "shield_text", None)
    if mode == "shielded" and callable(shield):
        return _redact(shield, project, value)
    return value


def _release(bridge: Bridge, project: str, value: object) -> object:
    mode = _guard(bridge, project)
    if mode != "shielded":
        return value
    return _redact(getattr(bridge, "shield_text", None), project, value)


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
    """Register the bridge tools on a new server bound to `bridge`."""
    app = App(MCPServer("iterthink"))

    @app.mcp.tool(description="Projects opened on this machine.")
    def list_projects() -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], _run(bridge.projects))

    @app.mcp.tool(description="Files in the project. iterthink's own data is hidden.")
    def list_files(project: str) -> list[dict[str, Any]]:
        body = _run(lambda: bridge.files(project))
        return cast(list[dict[str, Any]], _opened(bridge, project, body))

    @app.mcp.tool(description="Versions, newest first. Optionally one file.")
    def history(project: str, path: str | None = None) -> list[dict[str, Any]]:
        body = _run(lambda: bridge.history(project, path))
        return cast(list[dict[str, Any]], _opened(bridge, project, body))

    @app.mcp.tool(description="Proposals. Default status is open.")
    def list_proposals(project: str, status: str = "open") -> list[dict[str, Any]]:
        kind = cast(ProposalStatus, status)
        body = _run(lambda: bridge.proposals(project, kind))
        return cast(list[dict[str, Any]], _opened(bridge, project, body))

    @app.mcp.tool(description=f"Read one file. {_CONTENT}")
    def read_file(project: str, path: str) -> dict[str, Any]:
        body = _run(lambda: bridge.read(project, path))
        return cast(dict[str, Any], _release(bridge, project, body))

    @app.mcp.tool(description=f"Keyword search. {_CONTENT}")
    def search(project: str, query: str) -> list[dict[str, Any]]:
        body = _run(lambda: bridge.search(project, query))
        return cast(list[dict[str, Any]], _release(bridge, project, body))

    @app.mcp.tool(description=f"Diff two states of a file. {_CONTENT}")
    def diff(
        project: str, path: str, base: str | None = None, target: str | None = None
    ) -> dict[str, Any]:
        body = _run(lambda: bridge.diff(project, path, base, target))
        return cast(dict[str, Any], _release(bridge, project, body))

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

    _task_tools(app, bridge)
    return app


def _task(bridge: Bridge, name: str, *args: object) -> object:
    found = getattr(bridge, name, None)
    if not callable(found):
        raise ToolError("tasks are not available")
    return _run(lambda: found(*args))


def _task_tools(app: App, bridge: Bridge) -> None:
    """Task tools. A bridge without them still lists the tools and refuses the call."""

    @app.mcp.tool(description="Tasks on the board.")
    def list_tasks(project: str) -> list[dict[str, Any]]:
        body = _task(bridge, "tasks", project)
        return cast(list[dict[str, Any]], _release(bridge, project, body))

    @app.mcp.tool(description="Claim a ready Claude task. Does not start a process.")
    def claim_task(project: str, task_id: str, client: str) -> dict[str, Any]:
        body = _task(bridge, "task_claim", project, task_id, f"agent:{client}", client)
        return cast(dict[str, Any], _release(bridge, project, body))

    @app.mcp.tool(description="Set the current step shown on the task card.")
    def update_task(project: str, task_id: str, progress: str) -> dict[str, Any]:
        body = _task(bridge, "task_update", project, task_id, progress, "agent:mcp")
        return cast(dict[str, Any], _release(bridge, project, body))

    @app.mcp.tool(description="Ask the user a question. The task moves to Needs input.")
    def ask(project: str, task_id: str, question: str) -> dict[str, Any]:
        body = _task(bridge, "task_ask", project, task_id, question, "agent:mcp")
        return cast(dict[str, Any], _release(bridge, project, body))

    @app.mcp.tool(description="Finish the task and move it to Review.")
    def complete_task(project: str, task_id: str, summary: str) -> dict[str, Any]:
        body = _task(bridge, "task_complete", project, task_id, summary, "agent:mcp")
        return cast(dict[str, Any], _release(bridge, project, body))


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
