```
id: C8
status: draft
depends_on: [C2, C7, C15, C22]
```
# C8 · Tasks and agent runner

**Goal:** hand out work to several agents from a board; each returns
proposals, asks when it needs input, and competing proposals show up in review.

**Spec sections:** Tasks and agents (board) — all subsections; Agents (MCP);
Shared folders (claims); Agent rules; article §4.

**Ready when** the human has settled the contract (see `README.md` → Needs the
human): `TaskStatus` with the spec's eight statuses, and bridge methods for
`claim_task`, `update_task`, `ask`, `answer`, `complete_task`, `cancel_task`.
Until then this slice stays `draft`.

## Scope
- `iterthink/services/tasks.py`, `iterthink/services/agent_runner.py`, `bridge_real` task methods
- `iterthink/mcp/server.py` — task tools `list_tasks`, `claim_task`,
  `update_task`, `ask`, `complete_task`
- `iterthink/web/routes/tasks.py`, `templates/tasks/`, `static/js/task-board.js`,
  `static/css/c8-tasks.css`
- `defaults/agents.yaml` (**new seed file**)
- `tests/v2/services/test_tasks.py`, `test_agent_runner.py`, `tests/v2/web/test_c8_tasks.py`
- `scripts/strict_paths.d/C8.txt`

## Out of scope
- Re-running an agent automatically. Per-task drafts or branches (spec:
  "Later, with jj"). Creating tasks from the line (C3 calls `task_create`).

## Decided for you
- Task = `.iterthink/tasks/<id>.md` with the spec's front matter (`id`,
  `title`, `status`, `agent`, `inputs`, `scope`, `depends_on`, `budget`,
  `created_by`) and body. Every status change rewrites the front matter as a
  new version (snapshot + `task_status` event). Answers to questions are
  appended to the body.
- Columns: Backlog → Ready → Running → Needs input → Review → Done (or
  Rejected / Cancelled). Dragging between Backlog and Ready is the user's
  handover; the system moves the rest. Dependencies not Done block start.
- Review: the task's proposals (`produced_by` relation) wait in review; the
  card links to them. All accepted → Done; one rejected → Rejected with the reason.
- Agent profiles `.iterthink/settings/agents.yaml`, inherited (C15): `model_tier`,
  `blocks`, `rules`, `max_parallel`. An agent may call only its profile's
  blocks, only inside the task's `scope`, and only write via `propose`;
  `rules.yaml` (C7) applies on top.
- Runner: worker pool picks Ready tasks whose dependencies are Done, up to the
  global, per-profile and per-tier limits (local default 1, cloud default 4).
  Built-in agents: a tool loop over `llm_router` with bridge functions as tools,
  `egress.check(..., "agent", tier)`. Progress (step, tokens, elapsed) streams to
  the card over SSE.
- A running task holds a claim (C22) recording the machine as `runner`, so two
  machines never run one task.
- Budget exceeded → Needs input with "budget reached". Cancel stops the
  agent; proposals already made stay in review.
- Competing proposals on the same baseline: accepting one marks the others
  `conflict` (B1); the card offers "Run again on the new version", which
  moves the task back to Ready.
- A task's `scope` is shown on other cards whose scope overlaps.
- Audit: created, handed over, claimed, asked, budget hit, completed,
  cancelled are events with actor `agent:<profile>` and the task id; every
  proposal carries the task id.

## Acceptance
- [ ] `test_task_file_front_matter_and_each_status_change_is_a_version`
- [ ] `test_only_user_moves_backlog_to_ready`
- [ ] `test_dependency_blocks_start`
- [ ] `test_claimed_task_not_started_twice`
- [ ] `test_agent_limited_to_profile_blocks_and_scope`
- [ ] `test_budget_moves_task_to_needs_input`
- [ ] `test_ask_and_answer_appends_to_task_file`
- [ ] `test_task_outputs_are_proposals_linked_to_task`
- [ ] `test_all_accepted_moves_to_done_rejected_moves_to_rejected`
- [ ] `test_competing_proposals_show_in_review_and_run_again`
- [ ] `test_mcp_task_tools`
