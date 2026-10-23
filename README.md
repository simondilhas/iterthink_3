# iterthink 2.0

New tree. The running 1.x Flet app stays in `../iterthink_local_v2`.

This repo has the Python core copied from 1.x (`compare`, `services`, `persistence`, `db`, `contract`, `ai`, `defaults`) and the 2.0 shell (`web/`, the bridge, the slices). Flet is not a dependency.

| File | Role |
|---|---|
| `.cursor/rules/05-direction.mdc` | Always on. Short. |
| `docs/spec/` | The spec. Read the sections the current slice names. |
| `AGENTS.md` | How a run proceeds. |
| `docs/slices/` | The work, in order. |
| `docs/agent-prompt.md` | Paste this to start a run. |

```
uv sync --extra dev
uv run python scripts/check.py
```

## Run iterthink 2.0

From a fresh clone, `scripts/setup-agent-env.sh` installs uv if it is missing and syncs this repo. After that, the three commands below are enough.

**Desktop.** `uv run python -m iterthink.desktop` opens a local window. The page asks for a folder. Open one, then Make project. Your files stay where they are. iterthink writes its own data in that folder under `.iterthink/`. The list of folders opened on this machine is kept in the OS config directory: `~/.config/iterthink` on Linux, `~/Library/Application Support/iterthink` on macOS, and `%APPDATA%\iterthink` on Windows.

**Browser.** `uv run python -m iterthink.web` prints a link with a token. Open that link. It is the same app as the window, on `127.0.0.1`.

**MCP.** An agent connects over stdio. It can list what you have opened and propose a change. Accept, reject, save and restore stay in iterthink. File content stays on this machine while the project's egress is `shielded` (the value written when you make a project). To let an agent read files, set `egress: allowed` in `<project>/.iterthink/settings/project.yaml`.

Claude Desktop, in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "iterthink": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/iterthink", "python", "-m", "iterthink.mcp"],
      "env": {
        "ITERTHINK_PROJECTS": "/path/to/your/project"
      }
    }
  }
}
```

`ITERTHINK_PROJECTS` is the folder you made a project, or several folders separated by the system path separator. Leave `ITERTHINK_BRIDGE` unset. `ITERTHINK_BRIDGE=fake` is an in-memory bridge for tests; it forgets the session when the process stops.

## License

MIT, see [LICENSE](LICENSE). This covers the code, the spec in `docs/spec/`
and the file formats iterthink writes, so other tools can read and write an
iterthink project folder.
