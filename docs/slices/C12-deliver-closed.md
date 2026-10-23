```
id: C12
status: ready
depends_on: [B1]
```
# C12 · Work open, deliver closed

**Goal:** generate Word, Excel and PDF deliverables from your Markdown and CSV
(also through a client's template), and turn an edited file that comes back
into proposals.

**Spec sections:** Folder model (`exports/`); Mapping → `derived_from`;
article §7.

## Scope
- `iterthink/services/exports.py` (reuse 1.x DOCX export), `services/returned.py`
- `bridge_real.export`, `bridge_real.import_returned`
- `iterthink/web/routes/exports.py`, `templates/exports/`
- `tests/v2/services/test_exports.py`, `test_returned.py`
- `scripts/strict_paths.d/C12.txt`

## Decided for you
- Exports land in `.iterthink/exports/<source-stem>-<version-short>.<ext>`,
  never in the project root unless the user picks a folder; `derived_from`
  relation to the source version.
- Markdown → DOCX (with optional client `.dotx`/`.docx` template), Markdown →
  PDF, CSV → XLSX (openpyxl). No editing of generated files inside iterthink.
- Returned DOCX: extract text, align with the Markdown source (A4 text
  engine), create one proposal to the Markdown with reason "changes from
  <file name>". Returned XLSX → proposal to the CSV.
- Received files are kept as received (normal source files).

## Acceptance
- [ ] `test_docx_from_markdown_with_client_template`
- [ ] `test_xlsx_from_csv_keeps_umlauts`
- [ ] `test_exports_are_not_versioned_and_linked_to_source_version`
- [ ] `test_returned_docx_becomes_proposal_to_markdown`
- [ ] `test_returned_xlsx_becomes_proposal_to_csv`
