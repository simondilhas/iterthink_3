```
id: C18
status: done
depends_on: [B2, C9b, C16]
```
# C18 · Package the app

**Goal:** iterthink installs and starts as a desktop app on Fedora, Windows
and macOS, and nothing in it imports Flet.

**Spec sections:** What changes (remove Flet); Tech stack (pywebview);
The line → Voice input (macOS microphone entitlement).

**Already done in this tree:** no `studio/`, no `app_entry.py`, no Flet
dependency, no `compare/diff_card.py`; `compare/judge.py` holds the semantic
tie-break. This slice packages the desktop window and guards against Flet
coming back. It comes last so the build includes the `ifc` and `voice` extras.

**Set `ready`** by the human on 2026-10-23. PyInstaller is in
`pyproject.toml` (extra `package`) since 2026-10-26.

## Scope
- `iterthink/__main__.py` → starts `desktop.py`; `iterthink --version`
- `tests/v2/architecture/allowlists.py` — remove all Flet entries
- `packaging/` — PyInstaller spec per platform, macOS `Info.plist` with
  `NSMicrophoneUsageDescription` and the audio-input entitlement
- `tests/v2/packaging/test_package.py`
- `.github/workflows/desktop-build.yml` — **human-owned**: propose the change in the run report
- `scripts/strict_paths.d/C18.txt`

## Out of scope
- Deleting tests: there are no Flet tests in this tree. Code signing and notarisation.

## Decided for you
- PyInstaller one-folder per platform, including the `ifc` and `voice`
  extras; models (embeddings, STT) are not bundled, they download on first use.
- The build includes `web/templates/`, `web/static/` (with `vendor/`),
  `defaults/` and `verify_log.py`.

## Acceptance
- [x] `test_core_imports_without_flet` — subprocess with a finder that blocks `flet`
- [x] Architecture tests pass with every Flet allowlist entry removed
- [x] `test_main_starts_desktop_and_version_prints`
- [x] `test_spec_includes_templates_static_defaults`
- [x] `test_macos_plist_has_microphone_description`
- [x] Linux build runs `--version` locally; CI change proposed in the run report
