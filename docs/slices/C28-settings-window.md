```
id: C28
status: done
depends_on: [C15, C3]
```
# C28 · Settings window

**Goal:** the three-dot menu opens one Settings page where every setting can be
seen and changed, with the place its value comes from.

**Spec sections:** Build order step 11 (Settings); UI style (conventions);
The line (three-dot menu); Folder model (workspace-level settings).

## Scope
- `iterthink/services/app_settings.py` — machine values in the user `config.yaml`, API keys in the keyring
- `iterthink/services/settings_window.py` — `SettingsWindowBridge` mixed into `RealBridge`: rows per section, set / clear, Ollama status, index status and rebuild, settings files
- `iterthink/services/settings_sections.py` — the section and row definitions
- `iterthink/services/settings.py` — `clear_value`, workspace values for a workspace folder given directly
- `iterthink/services/bridge_real.py` — mix in `SettingsWindowBridge`
- `iterthink/services/intent.py` — `use_local_model` moves to `SettingsWindowBridge`
- `iterthink/ai/local_model.py` — line and chat model names come from the caller
- `iterthink/web/routes/settings_window.py`, `iterthink/web/routes/settings.py`
- `iterthink/web/routes/home.py` — theme and shortcuts from the bridge
- `iterthink/web/templates/settings/`, `templates/home/index.html`, `templates/home/head.html`, `templates/project/nav.html`
- `iterthink/web/static/css/c28-settings.css`, `iterthink/web/static/js/it-shortcuts.js`
- `tests/v2/services/test_app_settings.py`, `tests/v2/services/test_settings_window.py`, `tests/v2/web/test_c28_settings_window.py`
- `scripts/strict_paths.d/C28.txt`

## Out of scope
- Company and cloud models for the line and chat (keys are stored, nothing calls them yet).
- Downloading Ollama models (the page shows "ollama pull …").
- Editing privacy shield categories (shown read-only).

## Interface
```python
class SettingsWindowBridge:
    def settings_sections(self, project: str | None) -> list[Section]: ...
    def set_window_setting(self, project: str | None, key: str, value: str, level: str, actor: str) -> Row: ...
    def clear_window_setting(self, project: str | None, key: str, level: str, actor: str) -> Row: ...
    def ollama_status(self) -> OllamaStatus: ...
    def settings_file(self, project: str | None, name: str, level: str) -> str: ...
    def save_settings_file(self, project: str | None, name: str, level: str, text: str) -> None: ...
    def index_status(self, project: str) -> dict[str, object]: ...
    def index_rebuild(self, project: str) -> dict[str, object]: ...
    def appearance(self) -> str: ...
    def shortcut_keys(self, project: str | None) -> dict[str, str]: ...
    def use_local_model(self) -> None: ...
```

## Decided for you
- One page, sections stacked in this order, left list of anchors: Models,
  Privacy, Appearance, Paths, Dictation, Prompts and checks, Search index,
  Storage and usage, Shortcuts. `/settings` from the start screen,
  `/p/{id}/settings` in a project (adds the project level, egress, index, storage).
- A control saves on change and returns its row with "Saved". Each row shows its
  source (default, machine, workspace, project) and "Use default" when overridden.
- Machine values live in the user `config.yaml`; a bridge with its own state
  folder (tests) uses `<state_dir>/config.yaml` instead.
- On the start screen, inherited values are written to the default workspace.
- Ollama status and model names load after the page (`hx-trigger="load"`), so
  rendering the page never waits for Ollama.

## Acceptance (tests first)
- [x] `test_machine_value_round_trip`
- [x] `test_unknown_machine_key_is_refused`
- [x] `test_machine_secret_goes_to_keyring_not_yaml`
- [x] `test_rows_carry_their_source`
- [x] `test_use_default_clears_an_override`
- [x] `test_start_screen_writes_inherited_values_to_the_default_workspace`
- [x] `test_ollama_status_with_a_fake_client`
- [x] `test_changing_the_line_model_reconnects`
- [x] `test_settings_file_refuses_invalid_yaml`
- [x] `test_menu_links_to_settings_on_start_screen_and_in_project`
- [x] `test_all_sections_render`
- [x] `test_change_posts_and_shows_saved`
- [x] `test_appearance_changes_root_tokens`
- [x] `test_invalid_yaml_is_refused_on_the_page`
- [x] `test_index_rebuild_from_the_page`
- [x] `test_ollama_status_fragment`
- [x] `test_shortcuts_reach_the_page`

## Done when
All acceptance tests pass, `tests/v2/web/test_c15_settings.py` stays green and
`scripts/check.py --full` is green.
