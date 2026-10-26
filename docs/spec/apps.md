# Ad-hoc apps
- Generated as one self-contained HTML file (+ optional JS module) by the AI
  for the task in the line.
- Stored in `<project>/.iterthink/apps/<slug>/index.html` with a
  `manifest.yaml` (purpose, inputs, created by, model, prompt).
- Rendered in a sandboxed iframe: `sandbox="allow-scripts"` without
  `allow-same-origin`, own CSP, no network. It talks to iterthink only through
  `postMessage` with a narrow bridge (`static/js/app-bridge.js`, server side
  `services/bridge.py`). Every call runs in core, scoped to the current project.
  - No access to settings, secrets, other projects or the LLM router directly;
    AI blocks go through the router with privacy shield and token logging.
  - The frame has no token and makes no requests to the API. The parent page
    receives bridge messages, checks them against the allowlist and calls the
    API with its token.
  - Delivery: the app HTML is loaded via `srcdoc` with its own CSP meta tag
    (`default-src 'none'; script-src 'unsafe-inline' <vendor origin>;
    style-src 'unsafe-inline'; img-src data: blob:`). Inline script is allowed
    inside the frame only; the app shell keeps its strict CSP. Vendor modules
    are served with `Access-Control-Allow-Origin: null` so module scripts load
    from the frame's opaque origin.

## Building blocks (bridge functions)
Ad-hoc apps compose these. The AI writes glue and layout, not logic.
Prefer an existing block over generated code; a missing block is a backlog
item for core, not something an app reimplements.

| Block     | Bridge functions                                              | Core module (exists / new)                         |
|-----------|---------------------------------------------------------------|----------------------------------------------------|
| Read      | `listFiles(glob)`, `readFile(path, version?)`, `history(path)` | persistence (exists)                               |
| Import    | `importPdf(path)`, `importDocx(path)`, `ocr(path)`, `planText(path)` | document_import, ocr_import, plan_text_extract (exists) |
| Compare   | `compare(path, base, candidate)` → ContentChange rows + render payload | compare/, plan_text_diff, pdf_visual_diff (exists) |
| Judge     | `runCheck(check_id, target)`, `impact(target)`                | checks_runner, impact_analysis_runner (exists)     |
| Find      | `search(query, kind?, in_history?, k?)` — hybrid, see Search  | services/rag (exists), services/search (new)       |
| Annotate  | `annotatePlan(path, page, pin)`, `comment(path, paragraph, text)` | plan_pdf_annotations, paragraph_user_comments (exists) |
| Model     | `queryIfc(path, query)`, `ifcProperties(path, guid)`, `ifcGlb(path, version?)` | engine_ifc (new)                     |
| Table     | `readTable(path)`, `diffTable(path, base, candidate)`         | engine_table (new)                                 |
| Language  | `spellcheck(text, lang?)`, `detectLanguage(text)`             | spell_resources (exists)                           |
| Write     | `propose(path, content, reason)` — CSV / MD / JSON only       | proposals → review (new)                           |
| Deliver   | `exportDocx(md_path, template?)`, `exportXlsx(csv_path)`, `exportPlanPdf(path)` | markdown_docx_export, plan_pdf_export (exists); xlsx (new) |

Writes always go through `propose`; nothing an app does reaches disk without
review. `Deliver` writes only to `.iterthink/exports/` (or the chosen location) and is logged.

## View components (for apps and screens alike)
Custom elements in `static/js/`, shared by built-in screens and ad-hoc apps:
`<md-preview>`, `<data-table>` (sort, filter, changed cells), `<plan-viewer>`,
`<ifc-viewer>` / `<ifc-diff>`, `<image-compare>`, `<diff-text>`, `<check-symbols>`,
`<simple-chart>` (bar / line from a CSV, new), `<form-fields>` (inputs that
write a JSON or CSV row via `propose`, new). Ported from `studio/` where a Flet
version exists.

## Examples
- Door schedule: `queryIfc(model, IfcDoor + Pset_DoorCommon)` → `<data-table>`
  → `propose("schedules/doors.csv")` → optional `exportXlsx`.
- Spec check: `importPdf(spec_v7)` → `compare(spec, v6, v7)` →
  `runCheck("project_impact")` → review.
- Fire rating audit: `queryIfc(model, FireRating)` + `search("EI 90")` →
  `<data-table>` of mismatches → `propose("checks/fire-ratings.csv")`.

## Lifecycle
- Ad hoc by default: removed from view when closed unless kept. "Keep"
  promotes it to a permanent tool listed in the explorer under the project.
- A discarded app's code and manifest move to `.iterthink/apps/.archive/`,
  because its proposals and audit entries reference it. Purged only with the
  project's audit export, never silently.
- Agent rules (`rules.yaml`) apply to apps exactly as to agents.
- App code changes (Mod+Enter in an app) are versions of the app file,
  reviewable like any other change.

## App builder
The builder is a guideline prompt plus task context plus validation.
Code lives in `services/adhoc_apps.py`; the prompt is a seed file.

### 1. Builder prompt (`defaults/app_builder.md`)
- Seeded into workspace `.iterthink/settings/` and merged on upgrade like `prompts.yaml`
  (new defaults added, changed defaults go through the review dialog).
  Overridable per workspace and project (folder model inheritance).
- Sections:
  1. Rules: one self-contained HTML file (+ optional module), no network,
     bridge calls only, writes only via `propose`, open formats only,
     existing blocks before own logic, plain vocabulary in the UI, theme
     tokens via CSS custom properties.
  2. Bridge reference: every function with signature, arguments, return shape
     and one example. **Generated** at startup from the bridge registry in
     `services/bridge.py` (docstrings + type hints), never written by hand,
     so the prompt cannot drift from the real API.
  3. Component reference: every custom element with attributes, events and
     one example. Generated from a registry in `static/js/components.json`.
  4. Example apps: three to five complete, working apps (door schedule, spec
     check, fire rating audit). Stored as real files in `defaults/app_examples/`
     and covered by tests, so examples always run against the current bridge.
- Output contract: the model returns JSON
  `{ "slug", "title", "purpose", "inputs": [...], "html": "...", "module": "..."? }`.
  Anything else is a failed attempt.

### 2. Task context (assembled per request)
- The user's line, verbatim.
- Project file list: paths, sizes, kinds. **No file contents.**
- Schemas where relevant, extracted locally: IFC classes and property sets
  present in the model, CSV headers, Markdown headings.
- Up to three kept apps whose `manifest.yaml` purpose matches the line (via
  local embeddings). The model adapts one instead of starting fresh.

### 3. Validation before the user sees the app
1. Parse the JSON contract.
2. Static check on the HTML / module:
   - no `fetch`, `XMLHttpRequest`, `WebSocket`, `import()` of remote URLs,
     `<script src>` or `<link href>` outside `/static/vendor/`
   - only allowlisted bridge function names
   - no `eval`, no `new Function`
   - size limit (e.g. 200 KB)
3. Run headless in the sandbox with the real bridge in dry-run mode
   (reads allowed, `propose` recorded, not applied). Capture console errors
   and uncaught exceptions.
4. On failure: send the error list back to the model with the previous output.
   Maximum 3 attempts, then show the user what failed in plain language.
5. On success: store under `.iterthink/apps/<slug>/` with `manifest.yaml`
   (purpose, inputs, created by, model, prompt version, attempts) and open it.

### Privacy model
- The model writes the app; it never sees the data. It receives the line,
  paths and schemas only. The app reads content at runtime through the bridge,
  locally.
- Egress `none` denies a company or cloud build: nothing is sent. `shielded`
  and `allowed` may use those tiers. `shielded` redacts pattern categories
  (email, phone, keys and similar) on the line, paths and schemas. Names,
  addresses, organisations and project names are not removed by that pass.
- Settings: app builder tier selectable separately (local / company / cloud),
  default = strongest configured model, since code generation needs it.

### Logging
- Every build is an AI action in the audit trail: line, prompt version, model,
  attempts, validation results, kept or discarded.
- Build failures and user corrections are collected per prompt version to
  improve the builder prompt and to find missing blocks for core.

## Implementation
- `web/pages/line.py`, `templates/line.html`, `static/js/the-line.js`
  (`<the-line>`: input, Enter handling, recall shortcut, dot state via SSE).
- `services/intent.py` (classification + plan), `services/adhoc_apps.py`
  (prompt assembly, generate, validate, repair loop, store, promote, discard),
  `services/bridge.py` (bridge registry + reference generator),
  `defaults/app_builder.md`, `defaults/app_examples/`, `static/js/app-frame.js`
  (`<app-frame>`: sandboxed iframe + bridge).
- Intent classification is logged like every AI action (model, prompt id,
  chosen mode, user correction if any). Corrections improve the prompt, not a
  hidden model.
