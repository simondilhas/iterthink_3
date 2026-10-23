# Slices — the whole app

A slice is one part of the 2.0 rewrite. The agent finishes it, writes the run
report, and starts the next slice that can start. It stops when nothing left
can start. This tree has no Flet app; C18 packages the desktop window.

Every slice builds against the bridge contract (`iterthink/services/bridge.py`).
Slices implement it. They do not change it.

```
id: A1
status: draft | ready | in-progress | review | done | blocked | dropped
depends_on: []
```

A slice is named by its `id:`. `depends_on`, the order table and every
reference elsewhere use that id. File names pad the number so they sort:
`C01-index-and-search.md` is slice `C1`, `C09b-ifc-3d.md` is slice `C9b`.

The agent sets `in-progress`, then `done` or `blocked`. `draft` means a human
has not checked it yet: the agent never starts a draft. `dropped` means the
spec no longer includes it.

## Order

One rule: **take the first slice in the list below that is `ready` and whose
`depends_on` are all `done`.** The list follows
`docs/spec/build-order.md`; `depends_on` is the gate.

| # | slice | depends on | spec build step |
|---|---|---|---|
| 1 | A0 Baseline | — | quality gate |
| 2 | A2 Event log + checkpoints | — | 1 Foundation |
| 3 | A3 Snapshots | — | 1 Foundation |
| 4 | A4 Diff engines | — | 1 Foundation, 2 Review |
| 5 | A1 Shell & files | — | 1 Foundation |
| 6 | A5 Review UI | — | 2 Review |
| 7 | A6 MCP server | — | Agents |
| 8 | B1 Real bridge | A2, A3, A4 | 1 Foundation |
| 9 | B2 Integration | A1, A5, A6, B1 | — |
| 10 | C21 Disk changes & tracked files *(draft)* | B1 | 1 Foundation |
| 11 | C22 Claims | B1 | Shared folders |
| 12 | C1 Index & search | B1 | 1 Foundation, 5 Panels |
| 13 | C13 Handover & audit | B1 | 1 Foundation |
| 14 | C17 1.x importer | B1 | 1 Foundation |
| 15 | C2 Egress & privacy shield | B1 | Principles |
| 16 | C15 Settings & seeds | B1, C2 | 11 Settings (service needed earlier) |
| 17 | C4 Documents | B1, C2 | 3 Document |
| 18 | C5 Chats | C1, C2, C4, C22 | 4 The line |
| 19 | C3 Line & intent | C1, C2, C4 | 4 The line |
| 20 | C16 Dictation | C3, C15 | 4 The line |
| 21 | C23 Workspaces & explorer *(draft)* | B1 | 5 Panels |
| 22 | C11 Impact checks | C1, C2 | 5 Panels |
| 23 | C25 Checks panel *(draft)* | C1, C2 | 5 Panels |
| 24 | C24 Import incoming files *(draft)* | B1 | Formats |
| 25 | C6 Ad-hoc apps | C3, C15 | 6 Apps |
| 26 | C7 Rules & auto verdicts | B1, C15 | Agent rules |
| 27 | C8 Tasks & agents *(draft)* | C2, C7, C15, C22 | 7 Tasks |
| 28 | C10 Plan PDFs | B1 | 8 Plans |
| 29 | C26 Images *(draft)* | B1 | Format engines |
| 30 | C27 Table components *(draft)* | C6 | 9 Tables |
| 31 | C9 IFC engine & change table | B1 | 10 IFC |
| 32 | C9b IFC 3D diff | C9 | 10 IFC |
| 33 | C12 Deliver closed | B1 | Formats |
| 34 | C14 Shared folders | C1, C22 | Shared folders |
| 35 | C19 Erase *(draft)* | C13 | needs a spec section |
| 36 | C18 Package the app *(draft)* | B2, C9b, C16 | What changes |
| — | C20 bexio | dropped | — |

## Needs the human before the run reaches it
These are contract, seed or spec changes. A slice that hits one records it
under Blocked and finishes its other items.

- **Contract `Mode`** has no `review` (spec: "Compare spec v6 and v7" → review). C3.
- **Contract `TaskStatus`** is `todo|running|review|done|failed`; the spec has
  `backlog|ready|running|needs-input|review|done|rejected|cancelled`. No task
  tools for `claim`, `update`, `ask`, `complete`. C8 stays draft until settled.
- **No per-change verdict** in the bridge (spec review: accept / reject / edit
  per change, `data-hash`, 409). A5 and C9 work per proposal until then.
- **`search`** has no `kind`, `in_history` parameters (spec Search → Bridge). C1.
- **`AppInfo.url`** says "on the app origin"; the spec delivers apps via
  `srcdoc`. C6 follows the spec.
- **`bridge_fake.py`** labels (`NotImplementedError("slice C2")` for
  `interpret`, `"slice C3"` for chats) use the old numbering.
- **Seeds:** intent prompt in `defaults/prompts.yaml` (C3). Three.js in
  `static/vendor/` (C9b).
- **Spec:** an Erase section (C19). An external timestamp service is not in
  the spec (C13 leaves it out).
- **Packaging tool:** PyInstaller is not in `pyproject.toml` (C18).
- **Drafts to confirm:** C21 (disk changes, tracked files), C23 (workspaces),
  C24 (incoming files), C25 (checks), C26 (images), C27 (table components).
  Each says what to confirm under *Decided for you (to confirm)*.

## Definition of Ready — check before setting `ready`
- [ ] Goal is one sentence a user would recognise.
- [ ] Scope lists every file to create or change; Out of scope names the neighbours.
- [ ] Bridge methods it implements are named; new internal functions have signatures.
- [ ] Every acceptance item is a named test with the behaviour it proves.
- [ ] *Decided for you* answers the questions a careful engineer would ask.
- [ ] No open *Blocked* question from an earlier run.
- [ ] All `depends_on` slices are `done`.
- [ ] The spec sections it names match `docs/spec/`. Where they disagree, the spec wins.

## Ownership (keeps parallel runs from colliding)
- Web routes: one module per slice in `iterthink/web/routes/` (see its `__init__.py`).
- Templates: `iterthink/web/templates/<slice-area>/`. Shared partials named in the slice.
- CSS: `iterthink/web/static/css/<slice>-<area>.css`, loaded automatically.
- Strict paths: `scripts/strict_paths.d/<slice>.txt`.
- Human-owned, never edited by slices: `services/bridge.py`, `services/bridge_fake.py`,
  `tests/v2/contract/`, `web/app.py`, `web/__main__.py`, `templates/base.html`,
  `static/app.css`, `static/vendor/`, `pyproject.toml`.
