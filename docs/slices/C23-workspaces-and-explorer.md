```
id: C23
status: done
depends_on: [B1]
```
# C23 · Workspaces and explorer

**Goal:** point iterthink at a folder full of projects; each first-level
subfolder is offered as a project, new projects without a place land in the
default workspace, and the explorer panel shows projects on top and flags
untracked files without ever moving them.

**Spec sections:** Folder model (workspaces, default workspace, first-level
subfolders, untracked files, "make this folder a project" / "ignore"); The
line → Recall and state ("new project <name>"); Build order step 5 (explorer).

**Confirmed** by the human on 2026-10-23: *Decided for you* is settled.

## Scope
- `iterthink/services/workspaces.py`, `bridge_real.open_folder` (workspace aware),
  `bridge_real.make_project` (relative path → default workspace)
- `iterthink/web/routes/home.py`: only the `home_line` rule for "new project"
- `iterthink/web/routes/explorer.py` (replaces A1's file panel route), `templates/explorer/`
- `tests/v2/services/test_workspaces.py`, `tests/v2/web/test_c23_explorer.py`
- `scripts/strict_paths.d/C23.txt`

## Out of scope
- Workspace settings inheritance (C15 reads it). Disk scans (C21).

## Decided for you
- Known workspaces are machine state (`<state_dir>/workspaces.json`). Opening
  a folder that contains subfolders but no `.iterthink/` adds it as a workspace.
- Each first-level subfolder is a project candidate: projects show with their
  name and open-proposal count; others get "Make project" and "Ignore".
  "Ignore" is stored in the workspace's `.iterthink/settings/ignore.yaml`.
- Files directly in the workspace folder are shown as untracked, with the
  same two actions; iterthink never moves them.
- A new first-level subfolder appearing (watchdog) shows a quiet "Make project?" prompt.
- The explorer is a panel (Mod+E), closed by default; projects on top, then
  the current project's tree.

Added by the human on 2026-10-23 (default workspace):
- The default workspace is `documents_root` from `defaults/config.yaml`
  (read through `iterthink.config`, no new key). `workspaces.default_workspace()
  -> Path` expands `~`, creates the folder on first use and adds it to
  `workspaces.json`. It is listed first among workspaces.
- `bridge_real.make_project(path)` with a relative path means "new project in
  the default workspace": `workspaces.new_project_dir(name) -> Path` creates
  `<default>/<name>`, then tracks it. Absolute paths behave as before (A1).
- Folder name = the typed name with `/ \ : * ? " < > |` and control
  characters removed and whitespace trimmed. An existing folder of that name
  gets " 2", " 3", … appended; an existing folder is never reused or touched.
- Start screen rule in `home_line`, checked before the project-name match:
  `new project <name>`, `create (a) (new) project <name>`,
  `neues Projekt <name>` → `make_project(Path(name))` → open `/p/{id}`.
  Without a name ("new project", "create a new project") → a fragment that
  turns the line into "Name of the new project"; the next Enter creates it.
- The FakeBridge does not create folders for relative paths. Test the rule
  against `RealBridge` in a temp dir with `documents_root` pointed there, and
  record the fake behaviour under Blocked (see slices README → Needs the human).

## Acceptance
- [x] `test_workspace_lists_first_level_folders_as_project_candidates`
- [x] `test_untracked_files_in_workspace_are_flagged_not_moved`
- [x] `test_ignore_is_remembered_per_workspace`
- [x] `test_new_subfolder_prompts_make_project`
- [x] `test_explorer_is_closed_by_default_and_projects_on_top`
- [x] `test_default_workspace_is_created_and_always_known`
- [x] `test_relative_make_project_creates_folder_in_default_workspace`
- [x] `test_new_project_name_is_sanitised_and_never_reuses_a_folder`
- [x] `test_new_project_rule_on_start_screen_creates_and_opens` (English and German)
- [x] `test_new_project_without_name_asks_for_one`
