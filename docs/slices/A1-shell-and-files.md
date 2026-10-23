```
id: A1
status: done
depends_on: []
```
# A1 · Shell, projects and files

**Goal:** open iterthink in a window, open a folder, make it a project, browse
its files, read and edit Markdown, view CSV, and search from the line.

**Spec sections:** Principles; Folder model; Tech stack → Frontend, Desktop
shell; The line (start screen).

**Direction:** the start screen is the line, full width. Explorer, history and review open on demand and stay closed until asked. The 1.x three-column layout is gone. Theme tokens come from `defaults/config.yaml` (`theme.dark` / `theme.light`).

## Scope
- `iterthink/web/routes/home.py`, `projects.py`, `files.py`, `search.py`
- `iterthink/web/templates/home/`, `project/`, `files/`
- `iterthink/web/static/css/a1-shell.css`
- `iterthink/web/static/js/it-shortcuts.js`, `it-folder-picker.js`
- `iterthink/desktop.py`
- `tests/v2/web/test_a1_*.py`
- `scripts/strict_paths.d/A1.txt`

## Out of scope
- History, diffs, proposals, log (A5). AI in the line (C3). PDF/IFC previews (C9, C10).

## Bridge methods used
`open_folder`, `make_project`, `projects`, `files`, `read`, `save`, `search`.
Run against `FakeBridge` (`ITERTHINK_BRIDGE=fake`); never import anything
from `iterthink` except the bridge and `iterthink.web`.

## Pages and routes (names in brackets are route names)
- `GET /` [home] — start screen: white, a pulsing dot, the line with
  placeholder "What do you want to do?". Below: opened projects, and an
  "Open folder" form (path field; in the desktop window also a "Choose…"
  button using the folder picker).
- `POST /open` [open_folder] — form `path` → fragment listing folders:
  projects link to `/p/{id}`, others get a "Make project" button.
- `POST /projects` [make_project] — form `path` → redirect to `/p/{id}`.
- `GET /p/{id}` [project] — full width: the line, then a project overview
  (file counts by kind). Nothing else on screen. Two buttons in the header:
  **Files** and (only if `has_route(request, "panel")`) **History**.
- `GET /p/{id}/explorer` [explorer] — the file panel, opened by **Files** or
  Mod+E and closed by Esc or the button: folders as `<details>`, files with
  kind icon and a badge with `open_proposals` when > 0. Loaded on click
  (`hx-get`, `hx-trigger="click"`), never on page load.
- **History** loads `/p/{id}/panel` into a closable side panel on click,
  never on page load.
- `GET /p/{id}/f/{path:path}` [file] — full width by kind:
  markdown rendered with markdown-it-py, "Edit" switches to a textarea;
  table (.csv/.tsv) as an HTML table, "Edit as text" switches to a textarea;
  other kinds: name, kind, size, "Preview arrives later".
  Supports `?line=N` to scroll to and highlight a line.
- `POST /p/{id}/f/{path:path}` [save_file] — form `text` → save; respond with
  the rendered view, `HX-Trigger: {"versions-changed": {"path": ...}}`, and a
  toast "Saved" (or "No changes").
- `GET /p/{id}/search?q=` [search] — results fragment under the line, live
  while typing (`hx-trigger="input changed delay:150ms"`), max 20, each
  `path · line · snippet` linking to the file at that line.
- `POST /p/{id}/line` [line] — Enter in the line: opens the top search hit;
  no hits → toast "Nothing found". (C3 later replaces this with intent.)

## Decided for you
- UI language English; all text lives in templates.
- Keyboard (`it-shortcuts`): Mod+K focus the line, Mod+S save in the editor,
  Mod+E toggle the file panel, Esc closes search results or the open panel.
  Mod = Cmd on macOS, Ctrl elsewhere.
- The AI never runs here. Nothing happens on typing except keyword search.
- `desktop.py`: start `create_app()` with uvicorn on 127.0.0.1 and a free port
  in a daemon thread, wait for `/health`, open a pywebview window titled
  "iterthink" at the token URL. Expose `choose_folder()` via `js_api` returning
  the selected path or `null`. `python -m iterthink.desktop` runs it.
  `it-folder-picker` shows "Choose…" only when `window.pywebview` exists.
- Paths in URLs are URL-encoded POSIX paths; umlauts and spaces must work.
- Errors come from the bridge; let the skeleton's handler render them.
- After save, the editor stays open with the saved text (no jump).
- No JavaScript framework; HTMX attributes first, custom elements only for
  shortcuts and the folder picker.

## Acceptance (TestClient + FakeBridge, `project_dir` fixture)
- [x] `test_home_shows_line_and_open_folder`
- [x] `test_open_folder_lists_folders_with_make_project`
- [x] `test_make_project_redirects_to_project`
- [x] `test_project_page_is_line_and_overview_only` — no file list, no panel loaded on page load
- [x] `test_explorer_lists_files_with_kinds_and_proposal_badge`
- [x] `test_markdown_is_rendered_and_editable`
- [x] `test_save_writes_file_returns_toast_and_trigger`
- [x] `test_save_without_changes_says_no_changes`
- [x] `test_csv_renders_as_table_with_umlaut_headers`
- [x] `test_file_url_with_spaces_and_umlauts` — `Pläne/Notiz Grundriss EG.md`
- [x] `test_path_outside_project_is_403`
- [x] `test_search_returns_hits_with_links_to_line`
- [x] `test_line_enter_opens_top_hit` and `test_line_enter_without_hits_toasts`
- [x] `test_history_button_only_if_panel_route_exists` — and it loads on click, not on load
- [x] `test_desktop_starts_server_and_window` — pywebview replaced by a fake
      module; asserts URL contains the token and `choose_folder` is exposed.
- [x] `test_js_files_are_ts_checked` — every file in `static/js/` starts with `// @ts-check`.
- [x] Manual check list in the run report: 5 steps you can click through tonight.
