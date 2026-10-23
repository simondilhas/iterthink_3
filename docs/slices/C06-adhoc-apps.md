```
id: C6
status: ready
depends_on: [C3, C15]
```
# C6 · Ad-hoc apps

**Goal:** ask for a tool ("door schedule from the model", "clean this CSV")
and get a small app that reads your data locally; keep it or throw it away.

**Spec sections:** Ad-hoc apps (all subsections: Building blocks, View
components, Examples, Lifecycle, App builder, Privacy model, Logging,
Implementation); Security (CSP); article §6.

## Scope
- `iterthink/services/adhoc_apps.py`, `bridge_real` app methods
- `iterthink/web/routes/apps.py`, `templates/apps/`
- `static/js/app-frame.js` (`<app-frame>`), `static/js/app-bridge.js`
  (loaded inside frames), `static/js/components.json`, `static/css/c6-apps.css`
- `defaults/app_builder.md`, `defaults/app_examples/*` (**new seed files**;
  later changes go through review)
- `tests/v2/services/test_adhoc_apps.py`, `tests/v2/web/test_c6_apps.py`
- `scripts/strict_paths.d/C6.txt`

## Out of scope
- `<simple-chart>`, `<form-fields>` (C27). `queryIfc` and the model blocks
  (C9): until C9 is done, the builder reference lists only blocks that exist.
- A second server origin: the spec delivers apps via `srcdoc`.

## Decided for you
- Storage: `.iterthink/apps/<slug>/index.html` (+ optional `module.js`) and
  `manifest.yaml` (purpose, inputs, created by, model, prompt version,
  attempts, status). `AppInfo.id` = slug.
- Builder output contract: JSON
  `{"slug", "title", "purpose", "inputs": [...], "html", "module"?}`;
  anything else is a failed attempt.
- Builder prompt `defaults/app_builder.md` with the spec's four sections. The
  bridge reference is generated at startup from `services/bridge.py`
  (docstrings + type hints) and the component reference from
  `components.json`; neither is written by hand.
- Task context: the line verbatim; file list (paths, sizes, kinds); schemas
  extracted locally (CSV headers, Markdown headings, IFC classes and property
  set names once C9 exists); up to three kept apps whose purpose matches (local
  embeddings). **No file contents, no row values.** Schemas pass the privacy
  shield (`egress.prepare`) before a company or cloud call.
- Builder tier from settings (C15 key `apps.builder_tier`, default the
  strongest configured). Because no content is sent, building works under
  egress `none` with a cloud tier (C2 already allows this for purpose `app_build`).
- Delivery: `<app-frame>` renders the app via `srcdoc` in
  `<iframe sandbox="allow-scripts">` (no `allow-same-origin`) with the CSP meta
  tag from the spec. The frame has no token and makes no requests; it sends
  `postMessage` calls that the parent checks against the allowlist and forwards
  to the API with its token. Vendor modules are served with
  `Access-Control-Allow-Origin: null`. The shell's CSP is not relaxed.
- Allowlist: the read blocks that exist (Read, Find, Compare, Table, Language,
  Import read-only) plus `propose`. No settings, secrets, other projects or
  router access. Writes only via `propose` (CSV / MD / JSON).
- Validation before showing: parse the JSON; static checks (no `fetch`,
  `XMLHttpRequest`, `WebSocket`, remote `import()`, `<script src>` / `<link href>`
  outside `/static/vendor/`, no `eval` / `new Function`, only allowlisted bridge
  names, ≤ 200 KB). Failure → send the errors back with the previous output,
  at most 3 attempts, then show what failed in plain words.
- The spec's headless dry run (step 3) needs a headless browser this project
  does not have. Do the static checks plus a dry-run call of every bridge name
  the code uses; record the headless step under Blocked.
- Mod+Enter in an app = ask the AI to change the app; the new code is a new
  version of the app file, reviewable as a proposal. Enter confirms the
  current field.
- Keep → status `kept`, listed in the explorer under the project. Discard →
  moved to `.iterthink/apps/.archive/<slug>/`. Closing an unkept app hides it.
- Every build is an audit event: line, prompt version, model, attempts,
  validation results; keep / discard are events too.
- Example apps each have a test. This slice ships the ones that need no IFC
  block (spec check; a CSV cleanup); door schedule and fire rating audit are
  added by C9 with their tests.

## Acceptance
- [ ] `test_builder_prompt_contains_structure_never_content`
- [ ] `test_bridge_reference_is_generated_from_bridge_py`
- [ ] `test_schemas_pass_privacy_shield_before_remote_call`
- [ ] `test_app_frame_uses_srcdoc_sandbox_without_same_origin`
- [ ] `test_app_reads_data_only_through_allowlisted_bridge`
- [ ] `test_app_cannot_write_files_only_propose`
- [ ] `test_validation_rejects_external_urls_and_eval`
- [ ] `test_three_attempts_then_plain_error`
- [ ] `test_keep_and_discard_move_files`
- [ ] `test_shell_csp_unchanged_when_app_open`
- [ ] `test_example_apps_run` (each example)
- [ ] `test_build_under_egress_none_sends_no_content`
- [ ] `test_build_is_logged_with_attempts`
