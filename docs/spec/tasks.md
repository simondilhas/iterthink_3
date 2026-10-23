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
- Needs input: the agent asked a question. The card shows it, the dot pulses,
  the user answers on the card (or via the line). Answers are appended to the
  task file.

## Agent profiles (`.iterthink/agents.yaml`, inherited)
```yaml
spec-checker:
  model_tier: cloud          # local | company | cloud
  blocks: [read, import, compare, judge, find, model, table, write]
  rules: default             # rules.yaml applies on top
  max_parallel: 2
```
- An agent can only use the bridge blocks its profile lists, only inside the
  task's `scope`, and only write via `propose`. `rules.yaml` still applies.

## Runner (`services/agent_runner.py`)
- Local orchestration: a worker pool picks Ready tasks whose dependencies are
  Done, up to the limits (global, per profile, per tier; local Ollama default
  1, cloud default 4).
- Built-in agents: a tool loop over `llm_router` with bridge functions as
  tools. External agents (Claude Code, other MCP clients) use MCP task tools:
  `list_tasks`, `claim_task`, `update_task(progress)`, `ask(question)`,
  `complete_task(summary)`. Both paths go through the same core.
- Progress streams to the card via SSE: current step, tokens used, elapsed.
- Budget exceeded → task pauses in Needs input with "budget reached".
- Cancel stops the agent; proposals already made stay in review.

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
- Task created, handed over, claimed, asked, budget hit, completed, cancelled
  are `audit_events` with actor `agent:<profile>` and the task id. Every AI
  action and proposal carries the task id.
