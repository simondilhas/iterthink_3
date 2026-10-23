```
id: A5
status: ready
depends_on: []
```
# A5 · History, review and log UI

**Goal:** see every version of a file with its changes, restore one, review
proposals and accept or reject them with a reason, and read the decision log
with its integrity status.

**Spec sections:** Principles (Track decisions, Nothing applied without a
verdict, plain vocabulary); article §4, §9.

## Scope
- `iterthink/web/routes/history.py`, `review.py`, `log.py`
- `iterthink/web/templates/history/`, `review/`, `log/`,
  `templates/partials/diff_text.html`, `partials/diff_table.html`, `partials/diff_other.html`
- `iterthink/web/static/css/a5-review.css`, `iterthink/web/static/js/review-keys.js`
- `tests/v2/web/test_a5_*.py`, `tests/v2/golden/fragments/`
- `scripts/strict_paths.d/A5.txt`

## Out of scope
- File tree, editor, line (A1). Plan and model diff views (C10, C9). Impact
  checks (C11). Automatic verdicts (C7).

## Bridge methods used
`history`, `diff`, `restore`, `proposals`, `proposal_diff`, `accept`,
`reject`, `log`, `verify`, `files`.

## Pages and routes
- `GET /p/{id}/panel?path=` [panel] — side panel fragment, fetched only when
  the user opens it (A1's History button, the dot, Mod+H); closable with Esc.
  Three tabs: **History** (for `path`, else the project), **Proposals (n)**
  open count, **Log**. While open it refreshes on `versions-changed`,
  `proposals-changed` (`hx-trigger="versions-changed from:body, proposals-changed from:body"`).
- `GET /p/{id}/versions/{version}?path=` [version] — main pane: the version's
  actor, time, message, changed files; diff of `path` (or each changed file)
  against the version before.
- `GET /p/{id}/diff?path=&base=&target=` [diff] — diff fragment.
- `POST /p/{id}/restore` [restore] — form `path`, `version`; `hx-confirm`
  "Restore this version of <file>? The current one stays in history."
  → toast "Restored", trigger `versions-changed`.
- `GET /p/{id}/proposals` [proposals] — list: reason, by whom, when, files, status filter.
- `GET /p/{id}/proposals/{pid}` [proposal] — main pane: reason, actor,
  baseline time, one diff per file, then **Accept** (optional reason) and
  **Reject** (reason required) forms.
- `POST /p/{id}/proposals/{pid}/accept` [accept] / `.../reject` [reject] →
  updated proposal view, toast, triggers `versions-changed` + `proposals-changed`.
  `Conflict` → the view shows "This proposal no longer fits the current
  file" with the conflict status, no crash.
- `GET /p/{id}/log` [log] — table newest first: time, who, what (summary);
  header badge from `verify`: "Log intact · N entries" or the error in red.

## Decided for you
- Text diff: paragraphs as cards; `stable` collapsed into "n unchanged
  paragraphs" (expandable); changes show `<del>`/`<ins>` from `Segment`s.
  Block kinds labelled in plain words: refined, modified, rephrased, added, removed.
- Table diff: an HTML table with changed cells highlighted (title shows the old
  value), added rows marked, removed rows struck through; columns from `columns`.
- Other kinds: summary line only.
- Every action button uses HTMX; no full page reloads.
- Actor display: `user:simon` → "simon", `agent:checker` → "agent checker".
- Times shown in local time (`Europe/Zurich` default, from `ITERTHINK_TZ`).
- Words: version, change, proposal, accept, reject, restore, history. Never
  Git/jj words (architecture test checks templates).
- The accept form never pre-fills a reason; reject requires one (server enforces via bridge).
- Verdicts are per proposal. The spec's review is per change (accept / reject /
  edit on each change fragment); the bridge has no per-change verdict yet.
  Build the change fragments so each one is its own element
  (`<section class="change" data-change="…">`) so per-change actions can be
  added later, and record the gap under Blocked in the run report.
- Keyboard (`static/js/review-keys.js`, in this slice's scope): j / k move
  between changes, a accept, r reject (focuses the reason field). Works
  without JS through the forms.

## Acceptance (TestClient + FakeBridge)
- [ ] `test_panel_has_three_tabs_and_open_count`
- [ ] `test_panel_is_not_loaded_on_page_load` — no `hx-trigger="load"` pointing at the panel
- [ ] `test_history_lists_versions_newest_first_for_path`
- [ ] `test_version_page_shows_text_diff_with_ins_del`
- [ ] `test_table_diff_highlights_cells_and_rows`
- [ ] `test_restore_confirms_restores_and_triggers_refresh`
- [ ] `test_proposals_list_and_detail_show_reason_actor_diff`
- [ ] `test_accept_applies_and_triggers_refresh`
- [ ] `test_reject_requires_reason` (422 fragment) and `test_reject_with_reason`
- [ ] `test_accept_after_conflicting_edit_shows_conflict_message`
- [ ] `test_log_shows_entries_and_intact_badge`
- [ ] `test_log_shows_broken_badge` — fake bridge with a tampered entry
- [ ] golden: `test_diff_text_fragment_golden`, `test_diff_table_fragment_golden`
- [ ] Manual check list in the run report.
