# iterthink 2.0

A local-first workspace for project work with AI. One line to start any task;
documents, chats and ad-hoc apps emerge from it; open files hold the results;
every change, human or AI, passes review and lands in a sealed log.
Change detection and impact judgment (1.x) become building blocks inside it.

2.0 replaces the Flet UI with a local web UI in a native window. The Python core
(compare, services, persistence, ai, db) stays and becomes the single source of
logic for the UI, agents and future sync. This file supersedes `.cursorrules`
where they conflict (notably "NO JavaScript, NO HTML/CSS").

# How to read this spec
Read `README.md` (this file) and only the files the current slice names.
Slices name spec *sections* by heading; the table says which file holds each.
Where a slice disagrees with the spec, the spec wins.

| file | sections |
|---|---|
| `folders.md` | Folder model · Source files stay, iterthink files move · Shared folders |
| `data.md` | Data model · Storage: files are the truth · Tables (index projection) · Mapping of 2.0 concepts |
| `stack.md` | What stays · What changes · Tech stack · Repository layout |
| `the-line.md` | The line · Core rule · First Enter decides the mode · Enter by mode · Recall and state · Voice input · Everything is a file |
| `apps.md` | Ad-hoc apps · Building blocks · View components · Examples · Lifecycle · App builder · Privacy model · Logging · Implementation |
| `formats.md` | Formats: work open, deliver closed · Format engines |
| `build-order.md` | Build order |
| `tasks.md` | Tasks and agents (board) |
| `search.md` | Search |
| `review.md` | Review screen |
| `agents.md` | Agent rules · Agents (MCP) |
| `conventions.md` | UI style · Logic rules · File size |
| `audit-and-security.md` | Audit trail · Security |


# Role & tone
- Act as a senior software engineer. Concise, technical, direct.
- Root cause first, then the fix as code or diff. No summaries, no filler.
- Distinguish source code from runtime/data state. Flag seed files
  (`defaults/*.yaml`) as seeds immediately.

# Principles
- Local-first. No account. Source files stay where they are: iterthink adapts
  to the user's existing folders and never moves, renames or reorganizes them.
  iterthink's own data travels with the project in `<project>/.iterthink/`.
- No lock-in. Source files stay in open formats and open without iterthink.
- Track decisions, not files. Every change ends in a verdict: a human decision,
  or an automatic one under a rule the user set in advance (`rules.yaml`
  `direct`), recorded as "auto · rule <id>".
- Nothing is applied without the user's decision. AI, agents and apps propose.
- One core, many surfaces. UI, ad-hoc apps (bridge), MCP and CLI call the same
  registry of core functions (`services/bridge.py`).
- Keyboard: `Mod` = Ctrl on Windows/Linux, Cmd on macOS. All shortcuts below
  use `Mod` and are configurable.
- Plain vocabulary in the UI: version, change, proposal, accept, reject, restore,
  history. Never Git terms.

# Prohibited
- No Node, npm, bundler or frontend framework without explicit discussion.
- No business logic in routes, templates or JS. Routes call core and render.
- No cloud dependency by default. Cloud LLMs only when the user configures them.
- No second change model next to `ContentChange`.
- No direct writes to the SQLite index and no log lines written outside
  `services/event_log.py`. No database file inside a project folder.
- No new entity tables. Things are `content` rows, links are
  `content_relations` rows, kinds come from the contract.

# Later (not 2.0)
- History backend: evaluate Jujutsu (`jj`, Git-compatible) with one repo per
  project. Automatic snapshots per save, operation log for undo, conflicts as
  state, Git remotes as thin sync. Fits the storage model: `versions/` and
  `log/` are already plain, append-only files.
  Wrap it in one module (`persistence/vcs.py`); nothing else calls `jj`.
- Sync across devices: implement `sync_outbox` against that remote (e.g.
  self-hosted Forgejo), large files via Git LFS.
- Team review, {yourcompany}os workflow triggers on approval.
