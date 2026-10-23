```
id: C9
status: ready
depends_on: [B1]
```
# C9 · IFC engine and change table

**Goal:** compare two versions of a building model and see every change —
properties and geometry — as one table you can filter, mapped onto the change
contract.

**Spec sections:** Tech stack → IFC; What stays → contract/ (all formats map
onto `ContentChange`); Mapping → IFC element changes; Format engines; Review
screen → Rendering by kind (model); Ad-hoc apps → Building blocks (Model).

## Scope
- `iterthink/compare/engine_ifc.py` (registered in `engines.py`): element
  matching, categories, property and geometry rows, volumes
- `iterthink/web/routes/models.py`, `templates/models/`, `static/css/c9-models.css`
- `templates/partials/diff_model.html` (new partial used by A5's review for `kind="model"`)
- `defaults/app_examples/` — door schedule and fire rating audit (new seed files, with tests)
- `tests/v2/compare/test_engine_ifc.py`, `tests/v2/web/test_c9_models.py`,
  small IFC fixtures in `tests/v2/fixtures/ifc/`
- `scripts/strict_paths.d/C9.txt`

## Out of scope
- GLB files, the 3D view, `<ifc-viewer>` / `<ifc-diff>`, large-model progress (C9b).
- Applying part of an IFC change set: a model version is accepted or rejected
  as a whole in review. Editing IFC files. Plan PDFs (C10). Impact checks (C11).

## Interface
```python
Category = Literal["added", "removed", "reshaped", "moved", "props_only", "unchanged"]
class IfcEngine:  # FormatEngine
    kinds = ("model",)
    def diff(self, path: str, before: bytes | None, after: bytes | None) -> FileDiff: ...
def content_changes(diff: FileDiff) -> list[ContentChange]: ...
def query_ifc(data: bytes, ifc_class: str, psets: list[str]) -> list[dict[str, str]]: ...   # queryIfc block
def ifc_properties(data: bytes, guid: str) -> dict[str, dict[str, str]]: ...               # ifcProperties block
```

## Decided for you

### Matching and categories
- Elements are matched by GlobalId. Every element in either version gets
  exactly one category, checked in this order:
  1. `added`: only in the new version
  2. `removed`: only in the old version
  3. `reshaped`: shape in local coordinates differs
  4. `moved`: same shape, placement differs (translation or rotation)
  5. `props_only`: same geometry, at least one attribute or property differs
  6. `unchanged`
- A moved or reshaped element can also have property changes: the category
  stays geometric and `has_property_changes` is true.
- Shape fingerprint: tessellate with `ifcopenshell.geom` in local coordinates,
  round vertices to the tolerance, sort, sha256. Placement: 4×4 matrix compared
  with the tolerance. Tolerance 1 mm and 0.01°, module constants.
- Category names are display values in `FileDiff.details`, not contract enum
  values (the `Literal` above).

### Change rows
- One row per changed property: GlobalId, class, name, storey, path, old, new.
- Paths: `Pset_X.Property` for property sets and quantity sets,
  `attributes.Name` (and other direct attributes), `attributes.class` for a
  class change, `type.<Pset>.<Property>` for values inherited from the type.
- Added and removed elements and the geometric categories also get one row
  each (path `geometry.element`, `geometry.placement` or `geometry.shape`),
  so the table is the complete change list.

### Contract mapping
- Property rows → `ContentChange` with `change_class = PropertyChange`,
  `affected_subject_id = GlobalId`, `property_path` as above.
- Geometry rows → `ContentChange` with `change_class = GeometryChange`:
  - `geometry.element` for added and removed: `from_value` / `to_value` are
    the class name or null.
  - `geometry.placement` for moved: translation (mm) and rotation (degrees) as JSON.
  - `geometry.shape` for reshaped: bbox and volume as JSON.
- `FileDiff.kind = "model"`. `details["elements"]`: one entry per element with
  guid, class, name, storey, category, `has_property_changes`, `bbox_before`,
  `bbox_after`, `placement_delta`, `volume_before`, `volume_after`.
  `details["counts"]`: count per category. `details["rows"]`: the change rows.
  Volumes in m³ from the tessellated mesh (divergence theorem, numpy), rounded
  to 0.001.

### Table page
- `/p/{id}/models/compare?path=…&from=…&to=…`: counts per category at the top,
  then the table, rendered on the server as an HTML `<table>`. Filters
  (category, class, storey, pset) and sort are query parameters on an HTMX
  fragment. Changed values use the same `<ins>`/`<del>` styling as text and tables.
- Category badge colours are CSS custom properties in `c9-models.css`
  (`--it-cat-added` …), so C9b's 3D view and the legend share one source.
- Per-row accept / reject (spec: `intent_verdict` per change) needs a
  per-change verdict in the bridge, which does not exist. Render the table
  read-only and record the gap under Blocked.
- `ifcopenshell` comes from the `ifc` extra. Tests skip only if the extra is
  missing locally, and fail in CI.

## Acceptance
- [ ] `test_added_removed_changed_by_globalid`: matching by GlobalId, not by
      name or order.
- [ ] `test_each_element_gets_exactly_one_category`: all six categories from
      one fixture pair, using the precedence above.
- [ ] `test_moved_vs_reshaped`: a pure translation is `moved`, an extrusion
      depth change is `reshaped`, and both together are `reshaped`.
- [ ] `test_within_tolerance_is_unchanged`: a 0.5 mm shift is `unchanged`.
- [ ] `test_property_change_has_pset_path`: `Pset_WallCommon.FireRating`
      old → new as a `PropertyChange`.
- [ ] `test_type_and_attribute_paths`: `attributes.Name` and
      `type.<Pset>.<Property>` paths.
- [ ] `test_geometry_rows_map_to_geometry_change`: added, removed, moved and
      reshaped become `GeometryChange` rows with the paths above.
- [ ] `test_volumes_from_mesh`: a 1 × 1 × 1 m box gives 1.000 m³.
- [ ] `test_metadata_table_one_row_per_property`: the fragment renders rows
      with GlobalId, class, path, old and new, and filters by category and pset.
- [ ] `test_review_uses_model_partial_for_ifc_proposal`
- [ ] `test_query_ifc_block_returns_doors_with_pset`
- [ ] `test_example_apps_run` — door schedule, fire rating audit
