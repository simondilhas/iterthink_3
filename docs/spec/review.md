# Review screen
One candidate version against its baseline: aligned changes with diff and
accept / reject / edit. The server holds all state; the browser only displays it.

- `GET /review/{project}/{document}?base=&candidate=` renders `review.html`:
  header (source: user, AI margin action or agent; model; prompt id; reason),
  status bar (open / accepted / rejected counts), list of change fragments,
  "Accept all" / "Reject all".
- Each change fragment has its own HTMX actions:
  - `hx-post=".../changes/{change_id}/accept"`, `.../reject`, `.../edit`
  - `hx-target="closest .change"`, `hx-swap="outerHTML"`
  - The response is the updated fragment plus an out-of-band status bar
    (`hx-swap-oob`).
  - Every verdict is a `verdict` event in the log (actor, reason, baseline
    and candidate ids); the index updates from it.
- Rendering by kind, server-side wherever possible:
  - text: `word_diff_html` output, `<ins>` / `<del>`, kind badge
  - table: HTML `<table>`, changed cells `class="changed"`, old value in `title`
  - plan: `<plan-viewer>` with change pins over the page image
  - model: metadata changes as an HTML table, one row per changed property
    (GlobalId, class, Pset.Property, old, new); geometry as
    `<ifc-diff model-before="....glb" model-after="....glb" model-diff="....glb" changes="...json">`.
    The diff GLB colours each element by category (added, removed, moved,
    reshaped, properties only, unchanged); reshaped elements show added and
    removed volumes from IfcOpenShell booleans, with a before/after overlay as
    fallback. GLBs and change list produced by IfcOpenShell; clicking an
    element emits `ifc-select`, the table scrolls to the matching change
  - image: `<image-compare>` slider
- Concurrency: each fragment carries `data-hash` (sha256 of the candidate).
  If the file changed on disk meanwhile, the server returns 409 with a refreshed
  fragment marked outdated. Nothing is applied against a stale candidate.
- Live updates via SSE: new analysis results, disk changes, newer candidates
  swap in a notice at the top.
- Keyboard (`review-keys.js`): j / k move, a accept, r reject, e edit.
- The screen works without JS except the plan, model and image views.
