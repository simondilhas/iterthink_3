# Search
Hybrid by default: the user never chooses between keyword and semantic.
Builds on `services/rag/` (embeddings, query variants, local reranker,
`/f` and `/p` prefixes), adds keyword search.

## Pipeline (`services/search.py`)
1. Parse: `"exact phrase"` → keyword only for that phrase; `/f` filename;
   `/p <project>` scope; filters `kind:` (doc, plan, model, table, chat, app),
   `in:history` (older versions and change records), `since:<date>`.
2. Keyword: SQLite FTS5 (built in, no new dependency), BM25 ranking, unicode
   tokenizer with diacritics folding, trigram index for partial codes
   ("EI 9", "1.04"). Exact tokens such as norms, fire classes, room numbers
   and GlobalIds always match here.
3. Semantic: existing chunk embeddings (sqlite-vec), query variants only via
   the local tier (or with privacy shield).
4. Fuse: Reciprocal Rank Fusion of both lists (k = 60), then the existing
   local reranker on the top 50.
5. Group by document, best chunks first, snippet with highlights.

## What is indexed (one index, per project)
- Text documents and chats (existing chunking: parent / child).
- Imported working copies of PDF / DOCX; OCR text of plans with page and bbox,
  so a hit opens the plan at the spot.
- CSV: header + row text per row; a hit opens the table at the row.
- IFC: per element GlobalId, class, name, property sets as text; a hit opens
  the element in `<ifc-viewer>`.
- Change records (`content_changes` from / to values) and verdict reasons,
  under `in:history`: "when did EI 90 become EI 60?" finds the decision.
- Not indexed: archived apps' code, secrets, settings.
- Index updates on save and import (existing outbox pattern), in background;
  stale-index state shown in the results header.

## Where search lives
- In the line: intent "find / where / which document" routes to a results
  surface; Enter as always.
- Search panel (Mod+F in a document, Mod+Shift+F for the project): keyword
  results update while typing (no AI involved, local index only); semantic
  and rerank run on Enter. This is the one place results appear while typing,
  because no AI acts.
- Bridge / MCP: `search(query, kind?, in_history?, k?)` returns hits with
  `content_id`, version, location (paragraph, page + bbox, row, GlobalId),
  score and snippet.
- Chat and impact checks use the same function for context (RAG), scoped to
  the project.

## Results
- Each hit shows: document, location, snippet with highlights, match type
  (exact / meaning), version if not latest.
- Open = jump to the location in the right surface.
- "Make this an app" on a result list: hands the query and hits to the app
  builder (e.g. all doors with EI 30 → table).
- Searches are not logged in the audit trail unless their results feed an AI
  action; then the query and hit ids are recorded with that action.
