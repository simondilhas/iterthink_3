```
id: C1
status: done
depends_on: [B1]
```
# C1 · Index and search

**Goal:** search answers instantly across large projects, by keyword while
typing and by meaning on Enter, and the index can always be rebuilt.

**Spec sections:** Storage (projection, merge order, incremental indexing);
Tables (index projection); RAG scope (`services/rag/project_scope.py`).

## Scope
- `iterthink/services/indexer.py` — projection from logs, `.iterthink/versions/` and files
- `iterthink/services/index_store.py` — content rows (kept separate so each file stays within the size limit)
- `iterthink/services/search.py` — FTS5 keyword + embeddings + RRF + rerank
- `bridge_real.py` — `search` and `log` read from the index
- `tests/v2/services/test_indexer.py`, `test_search.py`, `tests/v2/invariants/test_rebuild.py`
- `scripts/strict_paths.d/C1.txt`

## Interface
```python
class Index:
    def __init__(self, db_path: Path, checkpoint_every: int = 500) -> None: ...
    def rebuild(self, project_dir: Path) -> None: ...
    def update(self, project_dir: Path) -> UpdateResult: ...   # applied, replayed_from
    def state_digest(self) -> str: ...
def keyword(index: Index, project: str, query: str, limit: int) -> list[SearchHit]: ...
def semantic(index: Index, project: str, query: str, limit: int) -> list[SearchHit]: ...
def hybrid(index: Index, project: str, query: str, limit: int) -> list[SearchHit]: ...
```

## Decided for you
- DB at `<state_dir>/index/<project-id>.db`, created from the existing 1.x
  SQLAlchemy models (`db/`, `persistence/`) as the index schema. The indexer
  fills, from events and files only:
  - `content`: one row per tracked file version (`lineage_id` = project path,
    `version_no`, `is_latest`), one per proposal draft (`status = candidate`).
  - `content_relations`: `proposes` (candidate → baseline version),
    `contains` (project → content).
  - `content_changes`: one row per changed block / cell from A4's `FileDiff`,
    mapped onto `ContentChange`; `intent_verdict` from `verdict` events.
  - `audit_events`: one row per log event.
  - FTS5 table `ix_fts` (unicode61, `remove_diacritics 2`) and a trigram
    table `ix_trigram` for partial codes ("EI 9", "1.04"); embeddings via the
    existing `services/rag/` chunking and sqlite-vec.
  Any other table the 1.x code expects stays empty; list them in the run report.
- `INDEX_VERSION` constant; mismatch → drop and rebuild.
- Sort key `(ts, machine, seq)`; late event → restore the last index snapshot
  below it (`VACUUM INTO <state_dir>/index/<id>.<seq>.db`), replay. Keep the last
  3. (These are index snapshots, not the log's `checkpoint` events.)
- Conflict = two `accepted` verdicts with the same baseline, different candidate.
- `bridge.search` stays keyword-only (live while typing): FTS5 BM25 plus
  trigram, with the spec's query parsing for `"exact phrase"`, `/f`, `kind:`,
  `since:`. `in:history` searches `content_changes` and verdict reasons.
  The contract's `search(project, query, limit)` has no `kind` / `in_history`
  arguments, so the filters are only available as query syntax; record that
  under Blocked as a contract question.
- `search.hybrid(...)` (FTS5 + embeddings + RRF k = 60 + existing local
  reranker on the top 50) is for the line on Enter (C3) and chats (C5). Local
  embeddings (fastembed) only; never a remote call.
- Indexing runs in a background thread after each event; the UI never waits.

## Acceptance
- [x] property: `test_shuffled_arrival_equals_full_rebuild`
- [x] property: `test_update_twice_is_noop`
- [x] `test_two_projects_never_mix`
- [x] `test_deleting_db_and_rebuilding_gives_same_digest`
- [x] `test_conflicting_accepts_surface_as_conflict`
- [x] `test_keyword_search_ranks_exact_word_first` and `test_search_under_50ms_for_2000_files` (slow)
- [x] `test_semantic_search_makes_no_network_calls`
- [x] `test_partial_code_matches_via_trigram` — "EI 9" finds "EI 90"
- [x] `test_query_syntax_kind_and_in_history`
- [x] `test_proposal_is_candidate_row_with_proposes_relation`
- [x] contract tests still pass for `real`
