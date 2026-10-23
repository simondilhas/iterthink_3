# iterthink 2.0

New tree. The running 1.x Flet app stays in `../iterthink_local_v2`.

This repo has the Python core copied from 1.x (`compare`, `services`, `persistence`, `db`, `contract`, `ai`, `defaults`) and the 2.0 shell (`web/`, the bridge, the slices). Flet is not a dependency.

| File | Role |
|---|---|
| `.cursor/rules/05-direction.mdc` | Always on. Short. |
| `.cursor/rules/iterthink-2.mdc` | The spec. Read the sections the current slice names. |
| `AGENTS.md` | How a run proceeds. |
| `docs/slices/` | The work, in order. |
| `docs/agent-prompt.md` | Paste this to start a run. |

```
uv sync --extra dev
uv run python scripts/check.py
```
