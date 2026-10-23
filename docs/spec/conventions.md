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
