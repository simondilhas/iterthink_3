# Folder model
- A workspace is any folder the user points iterthink at (local disk, external
  drive, network share). Several workspaces are allowed; the list of known
  workspaces is machine state. No fixed `Documents/iterthink` location.
- Each first-level subfolder is a project = one `Project` row. Deeper
  subfolders are plain folders inside the project. A user can also mark any
  single folder as a project without a workspace around it.
- The project is the unit of history, sealed log chain, RAG scope, checks
  context, sync and sharing. Never mix rows or RAG context across projects.
- `services/rag/project_scope.py` already scopes RAG by project: keep that
  boundary for every new feature (MCP tools take a `project` argument).

## Source files stay, iterthink files move
- iterthink never moves, renames, restructures or deletes source files on its
  own. It writes to a source file only when the user accepts a change to it.
  Moving files is a user action (or an accepted proposal), never automatic.
- Everything iterthink creates for a project lives in `<project>/.iterthink/`
  and moves with the folder (copy, rename, archive, hand over, sync):

```
<project>/
  ...source files, untouched...
  .iterthink/
    log/
      <machine-id>.jsonl  # append-only event log, one file per machine (the truth)
    versions/         # content-addressed snapshots (sha256) of tracked files
    apps/             # ad-hoc apps (+ .archive/)
    tasks/            # task files
    chats/            # chat files
    settings/         # project overrides: prompts, checks, rules, agents
    exports/          # delivery exports (DOCX / XLSX / PDF)
```

- User-facing outputs the user asks for (a new document, a schedule CSV) are
  written where the user says, default the project root, and are then normal
  source files.
- Workspace-level `.iterthink/` holds only workspace defaults (settings
  inheritance), no project data.
- Machine-level data stays in the OS app directory (`~/.config/iterthink`,
  `~/Library/Application Support/iterthink`, `%APPDATA%\iterthink`): known
  workspaces, downloaded models (embeddings, reranker, STT), UI state, and the
  per-project index databases (`index/<project-id>.db`), which are caches
  rebuilt from the project's files. Secrets stay in the OS keyring. Nothing
  there is the only copy of anything.
- On Windows, set the hidden attribute on `.iterthink/`.
- Opening a moved or copied project just works: paths inside `.iterthink/`
  are relative to the project root. A copied project gets a new project id
  on first open (asked: "copy or same project?") so chains do not fork silently.
- Handover / archive = the project folder as is. Audit export adds a
  verification script and a readable report into `.iterthink/exports/`.
- Files directly in the workspace folder (outside any project) are not
  tracked. The explorer shows them as untracked and offers "make this folder a
  project" or "ignore"; it never moves them. A new first-level subfolder
  prompts "Make project".
- Moving a file between projects (done by the user) is recorded as removed in
  one and added in the other, with a reference to the source.

## Shared folders (network drives, NAS, synced folders)
- No database lives on the share, so there is no SQLite locking problem.
  Several machines can open the same project at the same time.
- Each machine appends only to its own `log/<machine-id>.jsonl`; no two
  writers ever touch the same file. Other machines' logs are read, tailed
  and merged into the local index (file watcher + periodic rescan, since
  network file systems drop change notifications).
- Version snapshots are content-addressed and written once (write to a
  temp name, then rename), so concurrent writers cannot corrupt them.
- Task, chat and app files: one writer at a time per file via a short-lived
  claim (`<file>.claim` with machine, user, heartbeat). A second editor gets
  read-only with a banner; stale claims (no heartbeat for 2 min) can be taken
  over, logged as an audit event.
- Conflicting decisions (two machines accept different candidates for the same
  baseline) are detected when logs merge and surface in review as a conflict,
  like competing agent proposals. Never resolved silently.
- Detect cloud-sync folders (OneDrive, Dropbox, iCloud): logs and snapshots
  are safe there; warn that simultaneous edits of the same source file on two
  machines produce sync-client conflict copies, which iterthink then shows as
  separate candidates.
