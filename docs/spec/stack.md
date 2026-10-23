# What stays (core, reused as-is)
- `compare/` — alignment (TF-IDF + rapidfuzz), word diff, embedding cosine bands,
  LLM tie-break, slot kinds: stable, refined, modified, rephrased, added, removed.
  `paragraph_align.word_diff_html` already returns `<ins>`/`<del>` HTML: use it
  directly in templates.
- `services/` — import (PDF, DOCX, OCR), plan PDF text diff (bbox IoU), impact
  analysis runner, checks runner, RAG (sqlite-vec, fastembed), exports.
- `persistence/`, `db/`, `alembic/` — SQLAlchemy models and queries stay as
  the index schema (content lineage with `version_no` / `is_latest`,
  disk-state tracking by sha256). Their writes are rerouted through
  `services/event_log.py`; reads are unchanged. Migration: an importer turns
  an existing 1.x `store_db` into log events and snapshots once.
- `contract/` — the change contract: every change is a `ContentChange` row with
  `change_class` (PropertyChange | GeometryChange), `affected_subject_id`,
  `property_path`, `from_value`, `to_value`, `intent_verdict`, `change_source`.
  All formats, including IFC, map onto this contract. Do not invent parallel
  change models.
- `ai/` — `llm_router` (Ollama local default; company and cloud tiers via
  OpenAI-compatible, Anthropic, Gemini), privacy shield (regex + LLM redaction with
  placeholder reinject before company/cloud calls), token usage and cost tracking,
  local embeddings, OCR, keyring-backed secrets.
- Config pattern: bundled `defaults/*.yaml` seed runtime copies in the
  workspace `.iterthink/settings/` (overridable per project)
  (`prompts.yaml`, `checks.yaml`, `impact_checks.yaml`, `privacy_shield.yaml`,
  `config.yaml`); on upgrade, new defaults merge in and changed defaults go through
  a review dialog. Keep this pattern for every new config file.

# What changes
- Remove: Flet (`studio/`, `app_entry.py`, `compare/diff_card.py` flet spans).
- Add: `web/` (FastAPI, Jinja, HTMX, static), `desktop.py` (pywebview), `mcp/`.
- Core must not import UI code. `compare/diff_card.py` currently imports flet:
  split it into a pure judge module (stays in `compare/`) and drop the span builder.
  CI check: `grep -r "import flet" iterthink/` outside `studio/` fails the build.

# Tech stack
- Python 3.11+, `uv`, existing dependencies minus `flet`
- API and pages: FastAPI + Uvicorn on 127.0.0.1, random port, token auth
- Desktop shell: pywebview (WebView2 / WebKit / WebKitGTK), no browser controls
- Frontend: plain HTML, no build step
  - Jinja2 templates rendered server-side
  - HTMX for interactions; server holds state, returns HTML fragments
  - Vanilla JS ES modules only where needed, as custom elements
  - `// @ts-check` + JSDoc types; no TypeScript compile, no Node, no bundler
  - One `app.css` with custom properties; third-party JS vendored in
    `static/vendor/`, loaded via import map, works offline
- Live updates: Server-Sent Events (HTMX `sse` extension) for analysis progress,
  LLM streaming, file changes on disk
- IFC: IfcOpenShell for parsing, diff by GlobalId, GLB export per version and
  a diff GLB per version pair; Three.js (vendored) for the 3D view
- PDF plans: keep pypdfium2 rendering; overlays as positioned HTML/SVG over the
  page image, using existing normalized bbox data
- Tables: daff (diff), openpyxl (xlsx import and export)
- Voice: faster-whisper (local speech-to-text), sounddevice (audio capture)
- Agents: MCP server (official Python SDK) on the same core
- Quality: ruff, mypy (strict on new modules and `compare/`), pytest (keep the
  existing suite green)

# Repository layout (target)
```
iterthink/
  compare/  services/  persistence/  db/  alembic/  contract/  ai/  defaults/   # kept
  compare/engines.py      # new: FormatEngine registry (text, table, plan, model, image)
  compare/engine_ifc.py   # new: IfcOpenShell diff + GLB export
  compare/engine_table.py # new: daff for CSV / xlsx
  services/agent_rules.py # new: rules.yaml loading, inheritance, enforcement
  services/bridge.py      # new: registry of core functions for apps, MCP, UI
  services/proposals.py   # new: candidate versions (content rows + proposes relation)
  services/intent.py      # new: line → mode + plan
  services/adhoc_apps.py  # new: build, validate, repair, store, keep, discard
  services/dictation.py   # new: audio capture, streams transcripts
  services/event_log.py   # new: the only writer: append, fsync, hash chain, checkpoints
  services/indexer.py     # new: build / update the SQLite projection from logs + files
  services/audit.py       # new: verify chains and checkpoints, audit export
  services/importer_1x.py # new: one-time 1.x store_db → events + snapshots
  services/search.py      # new: hybrid search (FTS5 + embeddings + RRF + rerank)
  services/tasks.py       # new: task files, status transitions, dependencies
  services/agent_runner.py # new: worker pool, built-in agent loop, budgets
  ai/local_stt.py         # new: faster-whisper
  defaults/app_builder.md # new seed: builder prompt
  defaults/app_examples/  # new seed: example apps, covered by tests
  web/
    app.py              # FastAPI factory, token middleware, CSP headers
    deps.py             # project DB session, project root, merged settings
    routes/             # JSON: documents, versions, compare, checks, impact, settings
    pages/              # HTML pages + HTMX fragments, one module per screen
    events.py           # SSE: progress, LLM stream, disk changes, transcripts
    templates/
      base.html
      line.html           # start screen: dot + line
      document.html       # writer, full width; side panels open on demand
      chat.html
      app.html            # hosts <app-frame>
      review.html
      explorer.html
      settings.html
      fragments/
        change.html          # one change of any kind: badge, diff, actions
        status_bar.html
        impact_card.html
        check_symbol.html
        plan_overlay.html
        ifc_diff.html
    static/
      app.css
      js/
        the-line.js        # <the-line>: input, Enter rules, recall, dot state, voice hold
        md-editor.js       # <md-editor>: textarea + paragraph hooks, Mod+Enter
        md-preview.js      # <md-preview>
        diff-text.js       # <diff-text>
        data-table.js      # <data-table>: sort, filter, changed cells
        simple-chart.js    # <simple-chart>: bar / line from CSV
        form-fields.js     # <form-fields>: inputs that propose a row
        check-symbols.js   # <check-symbols>
        plan-viewer.js     # <plan-viewer>: zoom/pan, pins, revision clouds
        ifc-viewer.js      # <ifc-viewer> and <ifc-diff>: Three.js, by GlobalId
        image-compare.js   # <image-compare>: before/after slider
        task-board.js      # <task-board>: columns, drag to Ready, live progress
        app-frame.js       # <app-frame>: sandboxed iframe host
        app-bridge.js      # postMessage bridge, loaded inside app frames
        review-keys.js     # j/k move, a accept, r reject, e edit
        components.json    # component registry for the builder prompt
      vendor/              # htmx, htmx-ext-sse, three (+ GLTFLoader)
  mcp/
    server.py            # exposes bridge registry functions as MCP tools
  desktop.py             # starts Uvicorn thread, opens pywebview window
  __main__.py            # `iterthink` launches desktop.py
```
