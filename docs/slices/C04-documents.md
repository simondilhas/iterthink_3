```
id: C4
status: done
depends_on: [B1, C2]
```
# C4 · Documents

**Goal:** write Markdown full width; Mod+Enter on a paragraph asks the AI to
discuss, edit or evaluate it, and its answer arrives as a proposal you accept
or reject.

**Spec sections:** Build order step 3 (Document); The line → Enter by mode;
article §5, §7 (work open); Principles (AI proposes); Logic rules.

## Scope
- `iterthink/services/documents.py`
- `iterthink/web/routes/documents.py`, `templates/documents/`,
  `static/js/md-editor.js`, `static/js/md-preview.js`, `static/css/c4-documents.css`
- `tests/v2/services/test_documents.py`, `tests/v2/web/test_c4_documents.py`
- `scripts/strict_paths.d/C4.txt`

## Out of scope
- Opening a new document from the line (C3 calls `documents.create`). Recall
  via `/` (C3 handles the `it-recall` event). Dictation (C16). Rules that
  auto-accept AI edits (C7).

## Interface
```python
def create(bridge: Bridge, project: str, folder: str, name: str, title: str, actor: str) -> str: ...  # path
def margin_actions(project_dir: Path) -> list[MarginAction]: ...   # from prompts.yaml
def run_margin_action(project_dir: Path, *, path: str, paragraph: int, selection: str | None,
                      action_id: str, instruction: str | None, router: Router) -> Iterator[str]: ...
```

## Decided for you
- `GET /p/{id}/doc/{path:path}` opens `<md-editor>` full width; side panels
  (history, review) open on demand only. Save (Mod+S) creates a version (A1's
  `save`, the user's own act). A preview toggle uses `<md-preview>`.
- Paragraphs are found only through `compare.margin.split_paragraphs`.
- `/` typed at the start of an empty paragraph dispatches an `it-recall`
  event (`detail: {path}`) on the document; C3 brings the line back on it.
- Enter is a newline. **Mod+Enter** on the current paragraph or selection opens
  a small menu with the margin actions from `prompts.yaml` (Discuss / Edit /
  Evaluate, ids as in the seed) plus a free instruction field.
- The answer streams over SSE (`hx-ext="sse"`) into a side panel. Discuss and
  Evaluate stay as text there. Edit ends in `propose` on the document with
  the instruction as reason; the editor shows the change inline (A5 partials)
  with Accept / Reject. The AI never writes into the editor.
- Unsaved edits are saved before a proposal is requested, so the baseline is current.
- Calls go through `llm_router` with `egress.check(..., "chat", tier)`; the
  model call runs off the request thread.
- Every margin action is an audit event (action id, prompt version, model,
  paragraph index; text as blobs).
- `create`: file name and folder from the user (default project root, name
  suggested from the title), `<name>.md` with `# <title>` via `save`. An
  existing file is never overwritten (`Invalid`).

## Acceptance
- [x] `test_create_writes_md_where_user_says_and_never_overwrites`
- [x] `test_margin_actions_come_from_prompts_yaml`
- [x] `test_mod_enter_edit_creates_proposal_not_edit` — file unchanged until accept
- [x] `test_discuss_streams_over_sse_and_changes_nothing`
- [x] `test_accept_inline_updates_editor_and_history`
- [x] `test_unsaved_edits_saved_before_proposal`
- [x] `test_egress_none_uses_local_model_only`
- [x] `test_margin_action_is_logged`
