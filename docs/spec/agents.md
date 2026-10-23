# Agent rules
`.iterthink/rules.yaml`, inherited workspace → project like all settings.

```yaml
agents:
  default: propose          # propose | direct | deny
  direct:
    - "**/*.md:typos"       # minor text fixes only
  deny:
    - "contracts/**"
  propose_always:
    - "**/*.ifc"
    - "**/*.csv"
deletions: propose
```

- Applies to agents (MCP), ad-hoc apps and AI margin actions alike.
- `propose`: the edit becomes a candidate version in review.
- `direct`: applied without review because the user pre-approved this class of
  change; verdict recorded as "auto · rule <id>", chained, visible in history,
  restorable in one step.
- `deny`: refused, the refusal is logged.
- `direct` is never the default and never applies to deletions, IFC, plans or
  files under `deny`. Rules are enforced in core (`services/agent_rules.py`),
  never only in MCP or the bridge.

# Agents (MCP)
- MCP tools are the bridge registry: the same functions ad-hoc apps call
  (Read, Import, Compare, Judge, Find, Annotate, Model, Table, Language,
  Write via `propose`, Deliver), plus `list_projects` and the task tools
  (`list_tasks`, `claim_task`, `update_task`, `ask`, `complete_task`).
  No MCP-only logic.
- An agent session is bound to one project; every call carries it.
- Agents never write files. `propose` creates a candidate version that
  appears in review like any AI margin action or app output.
- Every agent action is logged with agent name, model and reason.
