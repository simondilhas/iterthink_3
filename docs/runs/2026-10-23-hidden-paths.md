# Run · 2026-10-23 · B1 follow-up · Hidden paths are not project files

**Status:** green
**Branch / PR:** dev · none
**Summary (2–3 lines, pasted into the PR):**
Any path with a segment starting with "." is now Forbidden in both bridges
(read, save, propose, history, diff, restore), and neither bridge lists such
files. An agent can no longer propose `.vscode/`, `.cursor/` or `.github/`
config files that iterthink would write on accept but never version.

## Acceptance
| item | test | result |
|---|---|---|
| Hidden paths refused by read, save and propose (both bridges) | `test_paths_outside_the_project_are_forbidden` (5 new cases) | pass |
| `files()` never lists hidden files (both bridges) | `test_files_hides_hidden_files` | pass |
| A proposal with one hidden path is refused whole | `test_proposal_with_one_hidden_path_is_refused_whole` | pass |
| MCP `propose` of `.cursor/mcp.json` is a tool error, nothing stored | `test_propose_of_hidden_config_is_refused` | pass |

`check.py`: green. `check.py --full`: red on
`tests/v2/e2e/test_day_one.py::test_restart_keeps_everything`, which fails the
same way without this change (see Surprises).

## Try it yourself (≤ 3 commands)
```
uv run pytest tests/v2/contract tests/v2/mcp -k "forbidden or hidden" -v
ITERTHINK_JJ=/bin/false uv run pytest tests/v2/contract -k real -q
```

## Blocked — needs your answer
None.

## Provisional decisions (taken, reversible)
- The rule matches `tracked_files` in `services/projects.py`: a hidden name at
  any depth (`notes/.draft.md`, `Pläne/.hidden/x.md`) is refused, not only at
  the top level. The `.iterthink`/`.jj` message is kept for those two folders
  (`projects.py:100-103`, `bridge_fake.py:110-113`).

## Proposed changes to rules, decisions, other slices
- `docs/spec/audit-and-security.md` → Security could say it outright: "Hidden
  files and folders are not project files; no bridge method reads or writes
  them."
- The real-bridge contract tests in `tests/v2/contract/conftest.py` are marked
  `jj` and skip without a `jj` binary, although `RealBridge` no longer uses jj
  (snapshots, slice A3). The real bridge's contract behaviour is therefore
  unchecked by default. Proposal: drop the `jj` mark and the `jj_bin`
  lookup for the `real` parameter.

## Files touched
- `iterthink/services/projects.py` (`relative()`)
- `iterthink/services/bridge_fake.py` (`_rel`, `_scan`), human-owned, edited
  with the human's approval
- `tests/v2/contract/test_bridge_contract.py`, human-owned, edited with the
  human's approval
- `tests/v2/mcp/test_server.py`

## Surprises
- `test_restart_keeps_everything` (e2e) already fails on `1f9aac5`: after a
  restart the home page does not list "P-101 Schulhaus". Not touched here.
- Users can no longer open dotfiles through iterthink. Before, the real bridge
  hid them from the file list but would still read or save one by exact path.
- The fake bridge now hides dotfiles like the real bridge; before, `_scan`
  listed them.
- `bridge_fake.py` was already over the 400-line limit before this change.
