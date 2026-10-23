# Build order
The line is the product's front door, but it routes into surfaces that must
exist first. Build bottom-up, ship the line as soon as it has places to go.

1. **Foundation** — `web/` shell, pywebview window, token, SSE, theme tokens,
   `services/bridge.py` registry, `services/event_log.py` + `services/indexer.py`
   (files as truth, SQLite as index), `services/audit.py`, 1.x importer.
2. **Review** — the safety layer everything depends on. Change fragments for
   text, accept / reject / edit, verdicts into the chain.
3. **Document** — `<md-editor>` full width. Save creates a version; margin
   actions from `prompts.yaml` (Discuss / Edit / Evaluate) via Mod+Enter,
   streamed via SSE, results land in review.
4. **The line** — start screen, intent routing to document, chat and review.
   Chat as `.md` files. Voice input.
5. **Panels** — search (hybrid, text first; plans, CSV, IFC as their engines
   land), explorer (projects at top, untracked files flagged), history,
   checks and impact (`checks.yaml`, `impact_checks.yaml` with RAG context),
   opened on demand.
6. **Ad-hoc apps** — bridge to apps, `<app-frame>`, builder, validation,
   keep / discard. First components: `<data-table>`, `<md-preview>`.
7. **Tasks and agents** — task files, board, runner with built-in agent loop,
   MCP task tools for external agents, competing-proposal handling in review.
8. **Plans** — plan compare in review, `<plan-viewer>`.
9. **Tables** — `engine_table` (daff), `<simple-chart>`, `<form-fields>`.
10. **IFC** — `engine_ifc`: element changes as `ContentChange` rows
   (`affected_subject_id` = GlobalId, `property_path` = Pset.Property), metadata
   change table, GLB per version, diff GLB coloured by change category,
   `<ifc-diff>`, `queryIfc` block for apps.
11. **Settings** — models (incl. app builder and STT tier), paths, prompts with
    merge review, privacy shield, RAG, token cost, shortcuts.

Port one surface at a time. Flet and the web UI may coexist on a branch during
migration; delete `studio/` modules as their replacement ships.
