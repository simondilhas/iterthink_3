# iterthink 2.0 — this tree

This is the new tree. The 1.x Flet app stays in `../iterthink_local_v2`.
The plan is `docs/spec/` (read the sections a slice names).
The short always-on rule is `.cursor/rules/05-direction.mdc`.
The agent builds `docs/slices/README.md` as far as it can, in one run.
`AGENTS.md` is how it works. `docs/decisions.md` is what is already settled.
Start a run with `docs/agent-prompt.md`.

## Already in the repo
| File | What it is |
|---|---|
| `docs/spec/` | The product. Wins where a slice disagrees. |
| `iterthink/services/bridge.py` | The contract: every function the UI, MCP, apps and CLI may call. |
| `iterthink/services/bridge_fake.py` | Real source files, history in memory, so the window can start before B1. |
| `tests/v2/contract/` | Behaviour tests every bridge implementation must pass. |
| `iterthink/web/app.py`, `base.html`, `app.css` | Web skeleton: token auth, errors, route discovery, layout regions. |
| `iterthink/web/static/vendor/` | htmx 2.0.11 and its SSE extension, offline. |

## What keeps a long run safe
| Mechanism | Where |
|---|---|
| Spec wins over a slice | `AGENTS.md`, `docs/decisions.md` |
| Decide, record as provisional, or block and continue | `AGENTS.md` |
| Signatures and edge cases fixed in advance | each slice → *Decided for you* |
| Contract tests the real backend must pass | `tests/v2/contract/` |
| One route module, template folder and CSS file per slice | `docs/slices/README.md` |
| Allowlists only shrink | `tests/v2/architecture/allowlists.py` |
| Version bytes are content-addressed snapshots, not jj | slice A3, decision D-003 rejected |

Run it with `docs/agent-prompt.md`.
