```
id: C5
status: done
depends_on: [C1, C2, C4, C22]
```
# C5 · Chats

**Goal:** back-and-forth questions about the project become chat files you
can find, reference, turn into a document, and hand over (or not).

**Spec sections:** Folder model (`.iterthink/chats/`); Mapping → chat;
The line → Enter by mode, Everything is a file; Search (RAG scope);
Tech stack → Live updates (SSE).

## Scope
- `iterthink/services/chats.py`, `bridge_real` chat methods
- `iterthink/web/routes/chats.py`, `templates/chats/`, `static/css/c5-chats.css`
- `tests/v2/services/test_chats.py`, `tests/v2/web/test_c5_chats.py`
- `scripts/strict_paths.d/C5.txt`

## Out of scope
- Starting a chat from the line (C3 calls `chat_start`). Claims themselves (C22).

## Decided for you
- File `.iterthink/chats/<id>.md`: front matter (id, title, created, references)
  then `## user · <ts>` / `## assistant · <ts>` sections. Plain Markdown, opens anywhere.
- Every message appended is a new version of the chat file (snapshot + event),
  like any document.
- Enter sends, Mod+Enter sends, Shift+Enter is a line break.
- Answers stream over SSE (`hx-ext="sse"`), chunks from `chat_send`; the model
  call runs off the request thread, via `llm_router` with
  `egress.check(..., "chat", tier)`.
- Answers cite project files as links (`references` updated); `search.hybrid`
  (C1) gives context, scoped to this project only.
- A chat never edits files. "Turn into proposal" on an answer → `propose`.
  "Turn into document" → a new `.md` via C4's `documents.create` with the
  chat's text (the user's own act); the chat links to it.
- While a chat is being written it holds a claim (C22 `claims.acquire`);
  a second window shows it read-only with a banner.
- Chats are excluded from client handover (C13).

## Acceptance
- [x] `test_chat_file_is_plain_markdown_and_roundtrips`
- [x] `test_each_message_is_a_version`
- [x] `test_answer_streams_over_sse`
- [x] `test_references_link_to_project_files`
- [x] `test_chat_cannot_change_files` and `test_turn_answer_into_proposal`
- [x] `test_turn_chat_into_document`
- [x] `test_second_writer_gets_read_only`
- [x] `test_context_never_crosses_projects`
