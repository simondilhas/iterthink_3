```
id: C10
status: done
depends_on: [B1]
```
# C10 · Plan PDFs

**Goal:** see a plan page with its changes marked on top, side by side or overlaid.

**Spec sections:** Tech stack → PDF plans (pypdfium2, overlays from normalised bbox).

## Scope
- `iterthink/services/plan_render.py` (page images cached per version)
- `iterthink/web/routes/plans.py`, `templates/plans/`, `static/js/it-plan-view.js`,
  `static/css/c10-plans.css`
- `tests/v2/services/test_plan_render.py`, `tests/v2/web/test_c10_plans.py`
- `scripts/strict_paths.d/C10.txt`

## Decided for you
- Page images rendered with pypdfium2 at 150 dpi, cached in machine state dir.
- Overlays: absolutely positioned HTML boxes from `FileDiff.details` bboxes
  (A4 plan engine); colours from app.css tokens (ins/del).
- Views: single (with overlays), side by side, swipe. Zoom and pan in the custom element.
- Existing 1.x annotations shown read-only if present.

## Acceptance
- [x] `test_page_image_cached_per_version`
- [x] `test_overlays_positioned_from_bbox`
- [x] `test_side_by_side_and_swipe_views_render`
- [x] `test_multi_page_navigation`
