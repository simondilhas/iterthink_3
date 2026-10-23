```
id: B2
status: ready
depends_on: [A1, A5, A6, B1]
```
# B2 · Integration: the app on real folders

**Goal:** tonight you open iterthink on a copy of a real project, edit,
let an agent propose via MCP, review, accept or reject, restore, and see an
intact log.

**Spec sections:** none new; this slice wires and proves.

## Start
Work on the current branch. A1, A5, A6 and B1 must be `done`.

## Scope
- Fixes inside A1, A5, A6, B1 modules needed for them to work together.
- `tests/v2/e2e/test_day_one.py` (marker `e2e`)
- `README.md` — section "Run iterthink 2.0" (desktop, browser, MCP).
- `scripts/strict_paths.d/B2.txt`

## Out of scope
- New features. Changing the contract (Blocked instead).

## Decided for you
- E2E tests use `create_app(bridge=RealBridge(state_dir=tmp))` and a
  TestClient; MCP tools are called through the server functions with the same bridge.
- If an A-slice behaves differently on the real bridge than on the fake,
  fix the A-slice code, not the contract; if the contract itself is wrong,
  record under Blocked with the exact case.
- README instructions must work from a fresh clone with
  `scripts/setup-agent-env.sh`.

## Acceptance
- [ ] `test_open_make_project_browse_edit_history` — through the web routes
- [ ] `test_agent_proposes_user_accepts_file_changes_log_intact` — MCP propose,
      web accept, file on disk changed, log verifies
- [ ] `test_agent_proposes_user_rejects_file_unchanged`
- [ ] `test_conflict_shown_in_review_after_user_edit`
- [ ] `test_restore_through_ui`
- [ ] `test_restart_keeps_everything` — new app + bridge on the same folders
- [ ] `test_mcp_refuses_content_until_egress_allowed`
- [ ] `test_sources_untouched_except_by_save_accept_restore` — `source_snapshot`
      across the whole flow
- [ ] Run report contains a 10-step manual script for tonight, including the
      MCP config line for Claude.
