# Tasks and agents (board)
Several agents work in parallel on tasks the user hands out. The board is a
built-in surface, not a generated app: it controls work and must behave the
same every time. Ad-hoc apps may embed `<task-board>` with a filter.

## Tasks are files
- One task = one Markdown file in `<project>/.iterthink/tasks/` with YAML frontmatter,
  indexed as a content row (kind `task`). Readable by any external agent or
  editor, versioned like any document, every status change is a version.

```markdown
---
id: t-0042
title: Check fire ratings in spec v7 against the model
status: ready            # backlog | ready | running | needs-input | review | done | rejected | cancelled
agent: spec-checker      # agent profile id, or "any"
runner: local            # copied from the profile at handover: local | cursor | claude
inputs: [specs/fire-protection.md, models/building.ifc]
scope: [specs/**, checks/**]   # paths the agent may propose changes to
depends_on: [t-0040]
budget: { tokens: 200000, minutes: 20 }
created_by: user
---
Compare every fire rating in the spec with the IFC door and wall properties.
List mismatches as checks/fire-ratings.csv. Do not change the spec.
```

## Columns
Backlog → Ready → Running → Needs input → Review → Done (or Rejected /
Cancelled). Drag between Backlog and Ready is the user's handover; the system
moves the rest.
- Review: the task's proposals (`produced_by` relation) wait in review. The
  card links straight to them. Accepting all proposals moves the card to Done;
  rejecting moves it to Rejected with the reason.
- Needs input: the agent asked a question. The card shows it, the dot turns orange,
  the user answers on the card (or via the line). Answers are appended to the
  task file.

## Agent profiles (`.iterthink/settings/agents.yaml`, inherited)
```yaml
spec-checker:
  runner: local              # local | cursor | claude
  model_tier: cloud          # local | company | cloud — privacy tier of the local runner
  blocks: [read, import, compare, judge, find, model, table, write]
  rules: default             # rules.yaml applies on top
  max_parallel: 2
cursor-coder:
  runner: cursor
  model_tier: cloud
  cursor_model: ""           # optional id from GET /v1/models; empty = Cursor's default
  blocks: [read, import, compare, judge, find, model, table, write]
  rules: default
  max_parallel: 2
claude-coder:
  runner: claude
  model_tier: cloud
  blocks: [read, import, compare, judge, find, model, table, write]
  rules: default
  max_parallel: 2
```
- The task's `agent` picks the profile. `runner` is which product does the
  work. `model_tier` stays the privacy tier. A Claude model id on a Cursor
  profile is still runner `cursor`.
- An agent can only use the bridge blocks its profile lists, only inside the
  task's `scope`, and only write via `propose`. `rules.yaml` still applies.
- The Cursor API key lives in the keyring. It is never written into a task
  file, a log line, or HTML.

## Runners
The board is the record. All three runners use the same task file, columns,
claim, and proposals. `services/agent_runner.py` is the pool. The Cursor HTTP
client is `ai/cursor_agent.py`, because remote clients live in `ai/` or
`services/egress.py`.

### Local
- The pool starts a tool loop over `llm_router` with bridge functions as
  tools, after `egress.check(..., "agent", tier)`.
- Progress on the card is the current step, tokens used, and elapsed time.

### Cursor
- Handing a task to Ready with a `cursor` profile launches a Cursor cloud
  agent. The API is Cloud Agents API v1 at `https://api.cursor.com` (public
  beta). Call shapes stay inside `ai/cursor_agent.py`.
- The project must have a remote Cursor can clone. Without one, the task
  moves to Needs input and nothing is launched.
- Egress must be `allowed`. The cloud machine clones the project, so
  `none` and `shielded` do not start it; the task moves to Needs input with
  the reason. The privacy shield is not a substitute.
- Order: claim the task and write a client-supplied agent id into the task
  file, then `POST /v1/agents` with that id, the task title and body as
  `prompt.text`, the remote, `autoCreatePR: false`, and `cursor_model` when
  set. A retry that receives "already exists" loads that agent instead of
  creating another. The response's run id and agent URL are written back
  (`cursor.agent_id`, `cursor.run_id`, `cursor.url`).
- The card follows `GET /v1/agents/{id}/runs/{runId}/stream`. Step text on
  the card comes from status and tool-call events. If the stream expires,
  the runner reads `GET /v1/agents/{id}/runs/{runId}`. Version 1 webhooks
  are not part of this plan.

| Board | Cursor run |
| --- | --- |
| Ready, user hands it over | `POST /v1/agents` |
| Running | `CREATING` or `RUNNING` |
| Needs input | the run is waiting on the user, or egress/remote blocked the launch |
| Review | `FINISHED` |
| Cancelled | cancel `POST /v1/agents/{id}/runs/{runId}/cancel` |

- An answer on the card is appended to the task file and sent as
  `POST /v1/agents/{id}/runs`.
- `FINISHED` moves the card to Review. The card links "Open agent" to
  `cursor.url`. Done still means the user accepted the task's proposals.
  A finished run with no proposals stays in Review until the user accepts
  that delivery or rejects the task.
- `mcpServers` is set only when the user has configured an iterthink MCP
  address the cloud machine can reach. The default bind is `127.0.0.1`,
  which a cloud agent cannot call. With a reachable address, the prompt
  tells the agent to report through `update_task`, `ask`, and
  `complete_task`, and to write only via `propose`. Without one, the board
  still shows the run; it does not invent proposals from the delivery.
- A delivery URL returned by the run is stored on the task as data. The
  UI word is "Open agent". Importing that delivery as proposals is out of
  scope.
- Cancel stops the Cursor run, then the normal cancel path. Proposals
  already made stay in review.
- Duration is recorded from the finished run. Tokens are recorded when the
  API returns them.

### Claude
- iterthink does not start Claude Code. Claude Code connects as an MCP
  client and calls `list_tasks`, `claim_task`, `update_task(progress)`,
  `ask(question)`, `complete_task(summary)`.
- `claim_task` enforces the profile's `max_parallel`. MCP egress rules
  apply to the content those tools return.
- Progress the client sends with `update_task` is the card's current step.

## Pool (`services/agent_runner.py`)
- The pool picks Ready tasks whose dependencies are Done, up to the limits
  (global, per profile, per tier; local default 1, cloud default 4). It
  starts `local` and `cursor` profiles. A `claude` profile waits for the
  client to claim it.
- A running task holds a claim (C22). The runner recorded on the claim is
  `local`, `cursor:<agent id>`, or `claude:<client>`. Two machines never
  run one task.
- Progress reaches the card via SSE.
- Budget exceeded → Needs input with "budget reached". For a Cursor run,
  the runner cancels the run first.

## Parallel work and conflicts
- Every proposal records its baseline version. Agents never wait for each
  other; conflicts are detected, not prevented.
- Two proposals on the same baseline of the same file → review shows them as
  competing; accepting one marks the other outdated and offers "rebase":
  the agent reruns its change on the new version (new candidate).
- Optional soft claims: a task's `scope` is shown on other cards that overlap,
  so the user sees conflicts coming before handing out work.
- Later, with jj: each running task works in its own draft (branch).

## From the line
- "Have an agent …" / "check all … in parallel" → intent `task`: creates one
  or more task files in Backlog with a proposed split, shown on the board for
  the user to adjust and move to Ready. Nothing runs before the handover.

## Audit
- Task created, handed over, claimed, launched, asked, budget hit, completed,
  cancelled are `audit_events` with actor `agent:<profile>` and the task id.
  A Cursor launch also records the agent id and run id. Every AI action and
  proposal carries the task id. The API key is never part of an event.
