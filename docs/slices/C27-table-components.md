```
id: C27
status: draft
depends_on: [C6]
```
# C27 · Table components

**Goal:** apps and screens can show a CSV as a sortable, filterable table, a
simple chart, or a form whose rows arrive as proposals.

**Spec sections:** Build order step 9 (Tables); View components
(`<data-table>`, `<simple-chart>`, `<form-fields>`); Ad-hoc apps → Building
blocks (Table, Write).

**Why draft:** confirm the component attributes before `ready`; they become
part of the builder prompt.

## Scope
- `static/js/data-table.js`, `simple-chart.js`, `form-fields.js`,
  entries in `static/js/components.json`
- `tests/v2/web/test_c27_components.py`
- `scripts/strict_paths.d/C27.txt`

## Decided for you (to confirm)
- `<data-table src=… changed=…>`: sort, filter, changed cells marked like A5's
  table diff. `<simple-chart src=… type="bar|line" x=… y=…>`: SVG, no library.
  `<form-fields target=… schema=…>`: on submit, one row via `propose` (CSV or JSON).
- All three read data through the app bridge inside frames and through the
  API in screens; no network.
- Each component has one example in `components.json`, so the builder prompt
  (C6) lists it.

## Acceptance
- [ ] `test_components_registered_in_components_json`
- [ ] `test_form_fields_submit_creates_proposal_not_write`
- [ ] `test_simple_chart_renders_svg_from_csv`
- [ ] `test_js_files_are_ts_checked`
