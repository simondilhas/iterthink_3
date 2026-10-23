# UI style (carried over from 1.x)
- Minimalistic. No explanatory paragraphs in settings: headings, labels,
  placeholders, tooltips (`title`). Exceptions: Privacy Shield and RAG disclaimers.
- Theme tokens from `config.yaml` (`theme.dark`, `theme.light`, `appearance`)
  become CSS custom properties on `:root`; never hardcode colours in templates.
- Monospace for the editor, sans-serif for the UI.
- Diffs: unchanged paragraphs hidden by default; `<ins>` / `<del>` with token
  colours; substantive changes (modified, rephrased with NEW verdict) get a
  high-contrast border.

# Logic rules (carried over)
- Paragraph splitting only through `compare.margin.split_paragraphs`.
- Semantic pipeline order: content hash → alignment → embedding cosine → LLM only
  in the uncertain band. Never call the LLM where hash or cosine decides.
- All LLM calls go through `ai.llm_router`; privacy shield applies to company and
  cloud tiers; token usage is recorded for every remote call.
- LLM and embedding work runs off the request thread (asyncio / worker threads);
  results stream via SSE. A request handler never blocks on a model.

# File size
Short files are easier for people and agents to read and change safely.

- Applies to every file: Python, templates, JS, CSS, tests, spec, docs, slices.
- Limits: a file ≤ 400 lines (test files ≤ 600); a function ≤ 60 lines.
  Fixtures, golden data, vendored files and lock files do not count.
- Over the limit → refactor before the slice is done: split by
  responsibility (code into modules in the same package, templates into
  partials, docs by topic), no behaviour change, tests green before and
  after, existing imports kept working (re-export).
- Existing files over 400 lines (e.g. `document_import.py`,
  `content_repo.py`, `store_db.py`, `llm_router.py`) are not split in bulk.
  A slice that changes one substantially splits the part it touches, only if
  the file is in its Scope. Otherwise it proposes the split in its run report.
- Human-owned files (`bridge.py`, `bridge_fake.py`, contract tests) are exempt;
  propose a split in the run report instead.
