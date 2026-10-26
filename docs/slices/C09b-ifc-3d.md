```
id: C9b
status: ready
depends_on: [C9]
```
# C9b · IFC 3D diff

**Goal:** see what changed in a building model's geometry as a 3D view
coloured by change category, next to C9's change table.

**Spec sections:** Tech stack → IFC; Review screen → Rendering by kind (model);
View components (`<ifc-viewer>`, `<ifc-diff>`); Ad-hoc apps → Building blocks
(`ifcGlb`).

## Scope
- `iterthink/compare/ifc_glb.py`: minimal GLB writer (numpy + `struct` + `json`)
- `iterthink/compare/engine_ifc.py`: per-version GLB, diff GLB, boolean
  difference volumes (extends C9)
- `iterthink/web/routes/models.py`, `templates/models/` (extends C9),
  `static/js/ifc-viewer.js` (defines `<ifc-viewer>` and `<ifc-diff>`)
- `tests/v2/compare/test_ifc_glb.py`, `tests/v2/compare/test_engine_ifc_3d.py`,
  `tests/v2/web/test_c9b_models.py`
- `scripts/strict_paths.d/C9b.txt`

## Out of scope
- The table, categories and contract mapping (C9).

## Prerequisite (human)
- Three.js vendored in `static/vendor/`: `three.module.js`, `GLTFLoader.js`,
  `OrbitControls.js`, listed in `VENDORED.md` and `THIRD_PARTY_NOTICES.md`.
  `static/vendor/` is human-owned. If the files are missing, finish the GLB
  writer and the engine items, record the viewer items under Blocked, and continue.

## Decided for you

### Diff geometry
- One diff GLB per pair of versions. Every mesh node is named by GlobalId and
  carries glTF `extras`: `{category, part}`. `part` is one of `after`,
  `before`, `added_volume` or `removed_volume`.
- What each category contributes:
  - `unchanged` and `props_only`: the after mesh
  - `added`: the after mesh
  - `removed`: the before mesh
  - `moved`: the after mesh plus the before mesh as a ghost
  - `reshaped`: `added_volume` = after − before and `removed_volume` = before −
    after, plus the after mesh as a translucent context mesh.
- Difference volumes come from IfcOpenShell's own geometry kernel: write a
  temporary IFC with two `IfcBooleanResult` (DIFFERENCE) solids in world
  placement and tessellate them. No mesh-boolean library.
- Fallback to `overlay` (before ghost + after solid, `diff_method = "overlay"`)
  when the kernel raises, returns an empty or invalid shape, or the element has
  more than 50,000 triangles. One element's failure never fails the diff.
- Adds to `details["elements"]`: `volume_added`, `volume_removed`, `diff_method`
  (`boolean` | `overlay` | null). `details["glb"]`: URLs of the before, after and diff GLBs.
- The GLB carries no colours. `<ifc-diff>` reads the category colours from
  C9's CSS custom properties, so the legend, the table badges and the 3D view
  share one source.
- Cached in the machine state directory, keyed by the sha256 of both files
  and an engine version constant. Never written into the project. Per-version
  GLBs (for `ifcGlb` and `<ifc-viewer>`) use the same cache.

### Page
- C9's compare page gets the 3D view and the table side by side; narrow
  windows stack them.
- `<ifc-diff model-before=… model-after=… model-diff=… changes=…>`. The default
  view is the diff GLB; a toggle shows before or after alone.
- Legend with one checkbox per category to show or hide it. `unchanged` is grey
  and translucent by default and can be hidden.
- Clicking an element emits `ifc-select` with the GlobalId: the table filters
  to that element and scrolls to it. Clicking a table row selects and frames
  the element in 3D.
- Works offline, with no network requests.
- Models over 50 MB: the diff runs as a background job with SSE progress
  (elements matched, booleans done or fallen back). The table fills in as rows arrive.

## Acceptance
- [x] `test_boolean_difference_volumes`: a wall lengthened by 1 m gives an
      `added_volume` equal to 1 m × height × thickness, and an empty
      `removed_volume`.
- [x] `test_boolean_failure_falls_back_to_overlay`: a forced kernel error sets
      `diff_method = "overlay"`, and the rest of the diff completes.
- [x] `test_diff_glb_nodes_carry_guid_category_part`: the GLB parses, and the
      node names and extras match `details["elements"]`.
- [x] `test_glb_writer_roundtrip`: `ifc_glb` output passes a glTF structure
      check (header, JSON chunk, BIN chunk alignment).
- [x] `test_glb_cached_outside_project`: no file is written under the project
      root, and a second call hits the cache.
- [ ] `test_model_compare_page_loads_viewer_and_legend`: `<ifc-diff>` has
      all four attributes, plus a legend with six categories.
- [ ] `test_large_model_reports_progress` (slow)
