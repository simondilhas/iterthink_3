```
id: C8
status: done
depends_on: [C2, C7, C15, C22]
```
# C8 · Tasks and agent runner

**Goal:** hand out work to several agents from a board. The user picks a
local runner, a Cursor cloud agent, or Claude Code. Each returns proposals
or a delivery, asks when it needs input, and competing proposals show up
in review.

**Spec sections:** Tasks and agents (board) — all subsections; Agents (MCP);
Shared folders (claims); Agent rules; article §4.

**Set `ready`** by the human on 2026-10-23, before the contract was settled.
The contract caught up on 2026-10-26: the spec's eight `TaskStatus` values and
`task_claim`, `task_update`, `task_ask`, `task_answer`, `task_complete`,
`task_cancel` are in `services/bridge.py`.

## Scope
- `iterthink/services/tasks.py`, `iterthink/services/agent_runner.py`, `bridge_real` task methods
- `iterthink/ai/cursor_agent.py` — Cloud Agents API v1 client (httpx, already a dependency)
- `iterthink/mcp/server.py` — task tools `list_tasks`, `claim_task`,
  `update_task`, `ask`, `complete_task`
- `iterthink/web/routes/tasks.py`, `templates/tasks/`, `static/js/task-board.js`,
  `static/css/c8-tasks.css`
- `defaults/agents.yaml` (**new seed file**)
- `tests/v2/services/test_tasks.py`, `test_agent_runner.py`, `test_cursor_runner.py`, `tests/v2/web/test_c8_tasks.py`
- `scripts/strict_paths.d/C8.txt`

## Out of scope
- Re-running an agent automatically. Per-task drafts or branches (spec:
  "Later, with jj"). Creating tasks from the line (C3 calls `task_create`).
- Cursor API v0, and v1 webhooks. Spawning Claude Code locally.
- Importing a Cursor delivery diff as proposals. Building a public address
  for iterthink's MCP (the `mcpServers` field is set only when one already
  exists).

## Decided for you
- Task = `.iterthink/tasks/<id>.md` with the spec's front matter (`id`,
  `title`, `status`, `agent`, `runner`, `inputs`, `scope`, `depends_on`,
  `budget`, `created_by`, and for a Cursor run `cursor.agent_id`,
  `cursor.run_id`, `cursor.url`). Every status change rewrites the front
  matter as a new version (snapshot + `task_status` event). Answers to
  questions are appended to the body.
- Columns: Backlog → Ready → Running → Needs input → Review → Done (or
  Rejected / Cancelled). Dragging between Backlog and Ready is the user's
  handover; the system moves the rest. Dependencies not Done block start.
- Review: the task's proposals (`produced_by` relation) wait in review; the
  card links to them. All accepted → Done; one rejected → Rejected with the reason.
  A Cursor run that finished with no proposals stays in Review until the user
  accepts that delivery (Done) or rejects the task.
- Agent profiles `.iterthink/settings/agents.yaml`, inherited (C15): `runner`
  (`local` | `cursor` | `claude`), `model_tier`, `blocks`, `rules`,
  `max_parallel`, and for Cursor an optional `cursor_model`. Seed one profile
  of each runner. An agent may call only its profile's blocks, only inside
  the task's `scope`, and only write via `propose`; `rules.yaml` (C7) applies
  on top. The Cursor API key is stored in the keyring.
- Pool: picks Ready tasks whose dependencies are Done, up to the global,
  per-profile and per-tier limits (local default 1, cloud default 4). It
  starts `local` and `cursor`. `claude` waits for MCP `claim_task`.
  `local` is a tool loop over `llm_router` after
  `egress.check(..., "agent", tier)`. Progress streams to the card over SSE.
- Cursor: follow Tasks and agents → Runners. Client in `ai/cursor_agent.py`.
  Tests fake the HTTP client. No call to `api.cursor.com` from the suite.
  Egress other than `allowed`, or a project with no remote, moves the task
  to Needs input and does not launch. The card says "Open agent".
- Claude: no process is spawned. `claim_task` enforces `max_parallel`.
- A running task holds a claim (C22) recording `local`, `cursor:<agent id>`,
  or `claude:<client>`, so two machines never run one task.
- Budget exceeded → Needs input with "budget reached". A Cursor run is
  cancelled first. Cancel stops the agent; proposals already made stay in
  review.
- Competing proposals on the same baseline: accepting one marks the others
  `conflict` (B1); the card offers "Run again on the new version", which
  moves the task back to Ready.
- A task's `scope` is shown on other cards whose scope overlaps.
- Audit: created, handed over, claimed, launched, asked, budget hit,
  completed, cancelled are events with actor `agent:<profile>` and the task
  id. A Cursor launch records the agent id and run id, never the API key.
  Every proposal carries the task id.

## Acceptance
- [x] `test_task_file_front_matter_and_each_status_change_is_a_version`
- [x] `test_only_user_moves_backlog_to_ready`
- [x] `test_dependency_blocks_start`
- [x] `test_claimed_task_not_started_twice`
- [x] `test_agent_limited_to_profile_blocks_and_scope`
- [x] `test_budget_moves_task_to_needs_input`
- [x] `test_ask_and_answer_appends_to_task_file`
- [x] `test_task_outputs_are_proposals_linked_to_task`
- [x] `test_all_accepted_moves_to_done_rejected_moves_to_rejected`
- [x] `test_competing_proposals_show_in_review_and_run_again`
- [x] `test_mcp_task_tools`
- [x] `test_cursor_profile_launches_on_handover_and_stores_ids`
- [x] `test_cursor_retry_reuses_the_stored_agent_id`
- [x] `test_cursor_stream_event_updates_card_progress`
- [x] `test_cursor_finished_moves_to_review_with_open_agent_link`
- [x] `test_cursor_answer_posts_a_follow_up_run`
- [x] `test_cursor_cancel_cancels_the_run`
- [x] `test_cursor_blocked_when_egress_is_not_allowed_or_remote_missing`
- [x] `test_claude_profile_is_claimed_over_mcp_and_not_launched`
- [x] `test_claude_model_on_a_cursor_profile_stays_runner_cursor`
