# Connect an agent

iterthink speaks MCP over stdio. The agent can list projects, read files when
you allowed it, and propose changes. It cannot accept, reject, save or restore.
A proposal waits until you decide it in iterthink.

Egress `none` refuses file lists, history, proposals and file contents.
`shielded` returns them with pattern redaction (email, phone, keys and similar),
including file names. Names, addresses, organisations and project names are
not removed. `allowed` returns the text as it is.

Set `ITERTHINK_PROJECTS` to the folders to open, separated by the system path
separator. `ITERTHINK_BRIDGE=fake` uses the in-memory bridge.

## Claude Desktop

`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "iterthink": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/iterthink", "python", "-m", "iterthink.mcp"],
      "env": {
        "ITERTHINK_BRIDGE": "fake",
        "ITERTHINK_PROJECTS": "/path/to/project"
      }
    }
  }
}
```

## Claude Code

`.mcp.json` in the project you open with Claude Code:

```json
{
  "mcpServers": {
    "iterthink": {
      "command": "uv",
      "args": ["run", "python", "-m", "iterthink.mcp"],
      "env": {
        "ITERTHINK_BRIDGE": "fake",
        "ITERTHINK_PROJECTS": "/path/to/project"
      }
    }
  }
}
```

## Cursor

`~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "iterthink": {
      "command": "uv",
      "args": ["run", "python", "-m", "iterthink.mcp"],
      "env": {
        "ITERTHINK_BRIDGE": "fake",
        "ITERTHINK_PROJECTS": "/path/to/project"
      }
    }
  }
}
```
