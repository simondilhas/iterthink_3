```
id: C26
status: draft
depends_on: [B1]
```
# C26 · Images

**Goal:** compare two versions of a photo or rendering with a before/after slider
and a marked region of change.

**Spec sections:** Format engines (image row); Review screen → Rendering by
kind (image); View components (`<image-compare>`).

**Why draft:** the spec names the engine in one table row; confirm the
pixel-diff threshold and the region output before `ready`.

## Scope
- `iterthink/compare/engine_image.py` (registered in `engines.py`)
- `templates/partials/diff_image.html`, `static/js/image-compare.js`,
  `static/css/c26-images.css`
- `tests/v2/compare/test_engine_image.py`, `tests/v2/web/test_c26_images.py`
- `scripts/strict_paths.d/C26.txt`

## Decided for you (to confirm)
- `.png .jpg .jpeg .webp`, decoded with Pillow (already in `pyproject.toml`).
- Pixel diff on images scaled to the same size; changed regions as normalised
  bboxes (0–1) in `details["regions"]`; `kind="image"`; summary in plain words
  ("2 areas changed"). Threshold a module constant.
- `<image-compare>`: slider, plus region boxes drawn over the after image.

## Acceptance
- [ ] `test_identical_images_are_none`
- [ ] `test_changed_region_has_normalised_bbox`
- [ ] `test_different_sizes_are_compared_scaled`
- [ ] `test_review_uses_image_partial`
