```
id: A4
status: done
depends_on: []
```
# A4 · Diff engines

**Goal:** any two states of a file become a `FileDiff` the UI can show:
paragraphs with word changes for text, cells and rows for tables, text
changes for plan PDFs.

**Spec sections:** What stays → compare/; Tech stack → Tables, PDF plans.

## Scope
- `iterthink/compare/engines.py` — registry and `diff(path, before, after) -> FileDiff`
- `iterthink/compare/engine_text.py`, `engine_table.py`, `engine_plan.py`
- `tests/v2/compare/test_engines.py`, `test_engine_text.py`,
  `test_engine_table.py`, `test_engine_plan.py`, `tests/v2/golden/diffs/`
- `scripts/strict_paths.d/A4.txt`

## Out of scope
- IFC (C9). Plan overlays UI (C10). Changing any 1.x algorithm or threshold.
- LLM tie-break: engines are deterministic; no model calls.

## Interface
```python
class FormatEngine(Protocol):
    kinds: tuple[FileKind, ...]
    def diff(self, path: str, before: bytes | None, after: bytes | None) -> FileDiff: ...

def register(engine: FormatEngine) -> None: ...
def diff(path: str, before: bytes | None, after: bytes | None) -> FileDiff: ...
```
`FileDiff`, `Block`, `Segment`, `CellChange` come from `iterthink.services.bridge`.

## Decided for you
- Text (markdown, text): use the existing paragraph alignment in `compare/`
  (TF-IDF + rapidfuzz, no embeddings, no LLM) to pair paragraphs; map slot kinds
  to `Block.kind` (stable, refined, modified, rephrased, added, removed); word
  segments from the existing word diff, as `Segment`s (not HTML).
  If the existing aligner needs embeddings for some kinds, use the
  non-embedding path and record it under Provisional decisions.
- Table (.csv, .tsv, .xlsx): daff for the alignment; row key = first column
  unless daff finds a better key; xlsx via openpyxl, first sheet only, cell
  values as strings. Fill `columns`, `cell_changes`, `added_rows`, `removed_rows`.
- Plan (.pdf): existing plan text diff (bbox IoU); `kind="plan"`, summary
  in plain words, `details={"pages": [...], "changes": [{"page", "bbox", "before", "after"}]}`
  with normalised bbox (0–1).
- Binary or unknown kind → `kind="binary"`, summary "file changed".
  `before == after` → `kind="none"`, "no changes". `before is None` → all added.
- Summaries in plain words, never Git or jj terms.
- Engines must not import `iterthink.services` except `bridge` (for the types).

## Acceptance
- [x] `test_registry_dispatches_by_kind` and `test_unknown_kind_is_binary`
- [x] `test_identical_is_none`, `test_new_file_is_all_added`, `test_deleted_file_is_all_removed`
- [x] text: `test_word_change_in_one_paragraph`, `test_paragraph_added_and_removed`,
      `test_moved_paragraph_is_not_add_and_remove` (if the aligner supports it),
      `test_umlauts_and_crlf`
- [x] table: `test_cell_change_by_key`, `test_row_added_removed`,
      `test_column_added`, `test_tsv_and_xlsx`
- [x] plan: `test_plan_text_change_has_page_and_bbox` (small PDF built in the test)
- [x] golden: `test_text_diff_golden` — fixture pairs in `tests/v2/golden/diffs/`
- [x] property: `test_text_diff_reconstructs_after` — joining non-removed blocks'
      `after` (and segments) gives the new paragraphs
- [x] `test_summaries_have_no_vcs_words`
