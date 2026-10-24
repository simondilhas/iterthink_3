```
id: C15
status: done
depends_on: [B1, C2]
```
# C15 · Settings and seeds

**Goal:** one settings page shows every setting, where its value comes from
(default, workspace, project), and lets you change it there.

**Spec sections:** What stays → Config pattern (defaults seed runtime copies,
merge on upgrade with review dialog); Folder model (workspace-level settings);
Build order step 11 (Settings).

The settings *service* is needed early: C6, C7, C8 and C16 read inherited
values through it. The page can stay simple; later slices add their keys.

## Scope
- `iterthink/services/settings.py` (`SettingsBridge` is mixed into `RealBridge` so
  `bridge_real.py` stays within the line limit)
- `iterthink/web/routes/settings.py` (extends C2's egress switch), `templates/settings/`
- `tests/v2/services/test_settings.py`, `tests/v2/web/test_c15_settings.py`
- `scripts/strict_paths.d/C15.txt`

## Out of scope
- The list of known workspaces and the explorer (C24). Rules semantics (C7),
  agent profiles (C8).

## Interface
```python
def get(project_dir: Path, key: str) -> SettingInfo: ...            # merged, with source
def all_settings(project_dir: Path) -> list[SettingInfo]: ...
def set_value(project_dir: Path, key: str, value: object,
              level: Literal["workspace", "project"], actor: str) -> SettingInfo: ...
def load_yaml(project_dir: Path, name: str) -> dict[str, Any]: ...  # merged file, e.g. "rules.yaml"
```

## Decided for you
- Order: bundled `defaults/` < workspace `.iterthink/settings/` < project
  `.iterthink/settings/`. Until C24 exists, the workspace is the project's
  parent folder if that folder has `.iterthink/settings/`.
- Merge: mappings merge key by key; lists and scalars replace.
- Keys this slice adds to the page (values from `defaults/config.yaml` where
  present, otherwise module constants recorded in the run report): model per
  tier, `apps.builder_tier`, `runner.max_parallel` (global, local 1, cloud 4),
  `dictation.language` (`auto`), `dictation.model` (`small`), shortcuts.
- On upgrade: new default keys merge in silently; changed defaults whose
  runtime copy was edited go to a review dialog (keep mine / take new / merge),
  the same for `prompts.yaml`, `checks.yaml`, `impact_checks.yaml`,
  `privacy_shield.yaml`, `config.yaml`, `rules.yaml`, `agents.yaml`, `app_builder.md`.
- Settings changes are logged (`settings` events) with old/new values.
- Storage per project shown with a trend: size of `.iterthink/versions/` and
  `.iterthink/log/`.
- Secrets never in YAML: API keys via keyring only.
- UI: headings, labels, placeholders, tooltips; no explanatory paragraphs
  except the Privacy Shield and RAG disclaimers (spec UI style).

## Acceptance
- [x] `test_inheritance_default_workspace_project`
- [x] `test_source_shown_for_each_value`
- [x] `test_load_yaml_merges_mappings_replaces_lists`
- [x] `test_upgrade_merges_new_keys_and_asks_for_changed`
- [x] `test_changes_logged`
- [x] `test_secrets_never_written_to_yaml`
- [x] `test_storage_growth_reported`
