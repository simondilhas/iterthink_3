# Data model
Follows the pragmaticBIM data contract (schema.pragmaticbim.ch, versioned;
`contract/` holds the enums in use). One content table, one relations table.
No feature gets its own entity table.

## Storage: files are the truth, SQLite is the index
- Source of truth = files in the project: source files, `versions/`
  snapshots, `log/*.jsonl`, task / chat / app / settings files.
- The event log records every state change as one JSON line: content version
  created, relation added, change detected, verdict given, audit event.
  Canonical JSON (sorted keys, UTF-8, no floats for ids), schema-versioned
  with the contract version.

```json
{"seq":1042,"ts":"2026-10-23T05:38:12Z","machine":"m-7f3a","actor":"user:simon","type":"verdict","project":"p-19c2","payload":{"change_id":"c-88e1","verdict":"rejected","reason":"EI 90 required"},"contract":"1.0.8","prev_hash":"…","hash":"…"}
```

- Every write goes through `services/event_log.py`: append the event to the
  local machine's log, fsync, then apply it to the index. Never write to the
  index directly; never write a log line from anywhere else.
- The SQLite database (`content`, `content_relations`, `content_changes`,
  `audit_events`, FTS5, embeddings, analysis) is a projection, stored
  machine-local, rebuilt by `services/indexer.py` from the logs and files.
  It remembers per log file the last applied offset and hash, so updates are
  incremental; a full rebuild is always possible and must give the same result.
- Schema changes to the index = bump index version and rebuild. Alembic stays
  only for the index schema, never as migration of user data.
- Merge order across machine logs: by `ts`, then `machine`, then `seq`;
  events are idempotent (`event id` = hash), so replays are safe.
- Projection tables below describe the index; their meaning is defined by the
  events that build them.

## Tables (index projection)

- `content`: every thing is a row, distinguished by `content_kind` /
  `canonical_type`, versioned by `lineage_id` + `version_no` + `is_latest`.
  Documents, plans, models, CSV tables, chats, ad-hoc apps, exports and
  candidate versions are all content rows.
- `content_relations`: every link is a row (versioned like content):
  derived_from (export → source version), proposes (candidate → baseline),
  produced_by (output → app), imported_from (working copy → original),
  references (chat → document), contains (project → content).
- Satellite tables stay as in 1.x: `files` + `content_file_links` (storage),
  `content_geometries` (geometry representations).
- Change records (`content_changes`, contract `Change` / `PropertyChange` /
  `GeometryChange`) and `audit_events` are audit records, not entities:
  outside the content graph; projections of the append-only, hash-chained log.
- Derived data (paragraph analysis, embeddings, annotations, comments,
  token usage) may keep its own tables; it is rebuildable or user input, never
  a second home for content.
- Mapping of 2.0 concepts:
  - proposal / candidate → content row with `status = candidate` +
    `proposes` relation to the baseline version; accept sets it latest
  - ad-hoc app → content row (artifact kind `app`), code as linked file,
    manifest in `attributes`; kept / discarded via `status`
  - chat → content row (artifact kind `text_document`), file in `.iterthink/chats/`
  - task → content row (kind `task`), file in `.iterthink/tasks/`; `depends_on` and
    `produced_by` (proposal → task) as relations
  - IFC element changes → `content_changes` with GlobalId as subject;
    elements themselves are not content rows unless a workflow needs them
- New kinds, statuses or relation types are added to the contract first
  (versioned enum), then used. No ad-hoc strings in code.
