```
id: C24
status: done
depends_on: [B1]
```
# C24 · Import incoming files

**Goal:** a DOCX or PDF someone sends you stays as received, and when you work
on it iterthink makes an open working copy (Markdown or CSV) linked to the original.

**Spec sections:** Formats: work open, deliver closed; Mapping →
`imported_from`; The line ("file dropped on the screen" → review or import);
What stays → services/ (document_import, ocr_import, plan_text_extract).

**Confirmed** by the human on 2026-10-23: *Decided for you* is settled.

## Scope
- `iterthink/services/incoming.py` — wraps the existing `document_import`,
  `ocr_import`, `plan_text_extract`
- `iterthink/web/routes/incoming.py`, `templates/incoming/`, drop handling in
  `static/js/it-drop.js`
- `tests/v2/services/test_incoming.py`, `tests/v2/web/test_c24_incoming.py`
- `scripts/strict_paths.d/C24.txt`

## Out of scope
- Returned deliverables (C12 turns them into proposals). Plans stay PDF (C10).

## Decided for you
- The original is kept as received: a normal tracked source file, compared as-is.
- "Work on this" creates `<stem>.md` (DOCX, text PDF, OCR for scans) or
  `<stem>.csv` (XLSX, first sheet) next to the original, as the user's own
  act (`save`), with an `imported_from` relation to the original's version.
- A file dropped on the screen: if a file with that name already exists in the
  project → copy it in as a new version and open the diff in review; otherwise
  ask where to put it (default project root), then the same.
- Plans (`.pdf` classified as plan by the existing classifier) are never
  converted; they open in C10's viewer.

## Acceptance
- [x] `test_docx_kept_as_received_and_md_copy_linked`
- [x] `test_scanned_pdf_goes_through_ocr`
- [x] `test_xlsx_becomes_csv_working_copy`
- [x] `test_dropped_file_with_existing_name_opens_review`
- [x] `test_plan_pdf_is_never_converted`
