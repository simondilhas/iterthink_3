```
id: C23
status: draft
depends_on: [B1]
```
# C23 · Workspaces and explorer

**Goal:** point iterthink at a folder full of projects; each first-level
subfolder is offered as a project, and the explorer panel shows projects on
top and flags untracked files without ever moving them.

**Spec sections:** Folder model (workspaces, first-level subfolders, untracked
files, "make this folder a project" / "ignore"); Build order step 5 (explorer).

**Why draft:** the spec's workspace model and A1's "Open folder → Make project"
overlap. A human should confirm how they fit before this is `ready`.

## Scope
- `iterthink/services/workspaces.py`, `bridge_real.open_folder` (workspace aware)
- `iterthink/web/routes/explorer.py` (replaces A1's file panel route), `templates/explorer/`
- `tests/v2/services/test_workspaces.py`, `tests/v2/web/test_c23_explorer.py`
- `scripts/strict_paths.d/C23.txt`

## Out of scope
- Workspace settings inheritance (C15 reads it). Disk scans (C21).

## Decided for you (to confirm)
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

## Acceptance
- [ ] `test_workspace_lists_first_level_folders_as_project_candidates`
- [ ] `test_untracked_files_in_workspace_are_flagged_not_moved`
- [ ] `test_ignore_is_remembered_per_workspace`
- [ ] `test_new_subfolder_prompts_make_project`
- [ ] `test_explorer_is_closed_by_default_and_projects_on_top`
