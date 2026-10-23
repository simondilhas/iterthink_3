```
id: A6
status: ready
depends_on: []
```
# A6 · MCP server

**Goal:** an agent (Claude, Cursor, others) can read a project and propose
changes, which then wait for your verdict in iterthink.

**Spec sections:** Principles (One core, many surfaces; Egress; AI proposes);
Tech stack → Agents.

## Scope
- `iterthink/mcp/__init__.py`, `iterthink/mcp/server.py`, `iterthink/mcp/__main__.py`
- `docs/mcp.md` — how to connect clients (config snippets)
- `tests/v2/mcp/test_server.py`
- `scripts/strict_paths.d/A6.txt`

## Out of scope
- Privacy-shield redaction of content (C2). Task runner (C8). HTTP transport.

## Tools (all take `project`; names are the MCP tool names)
| tool | bridge | content leaves? |
|---|---|---|
| `list_projects()` | `projects` | no |
| `list_files(project)` | `files` | no |
| `history(project, path=None)` | `history` | no |
| `list_proposals(project, status="open")` | `proposals` | no |
| `read_file(project, path)` | `read` | yes |
| `search(project, query)` | `search` | yes |
| `diff(project, path, base=None, target=None)` | `diff` | yes |
| `propose(project, changes: dict[str,str], reason, baseline=None)` | `propose` | no |

No tool accepts, rejects, saves or restores. Verdicts are human.

## Decided for you
- Official MCP Python SDK, `FastMCP`, stdio transport. `python -m iterthink.mcp`.
- Bridge from `get_bridge()`; projects opened via `ITERTHINK_PROJECTS`
  (os.pathsep-separated folders) at startup, each passed to `open_folder`.
- Actor: `agent:<client name from the MCP initialize request>`, fallback `agent:mcp`.
- Egress gate for tools marked "yes": allowed only when the project's egress
  is `allowed`. `shielded` and `none` → tool error: "This project keeps its
  content on this machine (egress: <value>). Change it in iterthink's
  settings to allow agents to read files." (Shielded redaction arrives in C2.)
- Results as compact JSON-serialisable dicts from the bridge dataclasses
  (`dataclasses.asdict`), diffs included.
- Bridge errors → MCP tool errors with the bridge's message.
- Tool descriptions say plainly that `propose` creates a proposal the user
  must accept, and that files are not changed.

## Acceptance (call the tool functions with FakeBridge; no subprocess needed)
- [ ] `test_tool_list_is_exactly_the_eight_tools` — no accept/reject/save/restore
- [ ] `test_list_projects_and_files`
- [ ] `test_read_file_allowed_when_egress_allowed`
- [ ] `test_content_tools_refused_when_egress_shielded_or_none` (parametrised)
- [ ] `test_metadata_tools_work_under_egress_none`
- [ ] `test_propose_creates_open_proposal_and_leaves_files` — `source_snapshot` equal
- [ ] `test_actor_comes_from_client_name`
- [ ] `test_bridge_error_becomes_tool_error`
- [ ] `test_server_starts_over_stdio` (marker `integration`) — spawn
      `python -m iterthink.mcp`, initialize, list tools, exit cleanly.
- [ ] `docs/mcp.md` contains working config for Claude Desktop, Claude Code and Cursor.
