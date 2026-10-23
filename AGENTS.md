# AGENTS.md — how to work on iterthink

Entry point for every coding agent (Cursor, Claude Code, others).
The architecture spec is `docs/spec/`. This file says how
to work; the spec says what to build; the slice says exactly what to do now.

**The spec wins.** Where a slice, this file, or `docs/decisions.md` disagrees
with `docs/spec/`, follow the spec. Record the disagreement
under Blocked and continue with work that does not depend on it. The open
disagreements are listed in `docs/decisions.md` under Conflicts.

**Keep going.** A slice is a unit of scope and tests, not a day. Finish the
slice you are on, write its run report, then start the next slice whose
`depends_on` are `done`. A blocked slice does not stop slices that do not
depend on it. Stop only when no remaining slice can start.

**Runs are unattended.** Nobody answers questions during a run. Write the run
report and continue. Everything below is written for that.

**The bridge is the contract.** `iterthink/services/bridge.py` defines what
every surface can do; `bridge_fake.py` implements it for UI and MCP work;
`tests/v2/contract/` says how it must behave. These are human-owned: you
implement against them and never change them. If the contract is wrong or
missing something, record it under Blocked with the exact case.

## Start of a run
1. Run `scripts/setup-agent-env.sh` if the environment is fresh.
2. Read this file, `docs/decisions.md`, your slice in `docs/slices/`, and only
   the spec sections the slice names.
3. Check the slice is `status: ready` and every `depends_on` slice is `done`.
   If not, skip it and take the next slice that is. If none can start, stop.
4. Work on the current branch. Set the slice to `status: in-progress`.
5. Run `uv run python scripts/check.py` once before changing anything.
   Whatever already fails is not yours: list it under Surprises and don't fix it.

## The loop
1. Write the acceptance tests named in the slice. Run them; they must fail
   for the right reason (missing function, wrong result), not import errors
   in unrelated code.
2. Implement the smallest change that makes them pass.
3. Run `uv run python scripts/check.py`; fix what it reports.
4. Commit after each green acceptance item: `A3: snapshot excludes log files`.
5. When all items pass: `uv run python scripts/check.py --full`.

## When something is unclear
Use the slice's **Decided for you** section first. If it doesn't cover it:

- **Internal and reversible** (naming, private helpers, data structures not
  visible outside the module): take the simplest option consistent with the
  spec, note it under *Provisional decisions* in the run report, continue.
- **Visible or hard to undo** (anything in AGENTS.md → Hard stops): do not
  guess. Note it under *Blocked* with the exact question and the options you
  see. Finish every acceptance item it doesn't affect, then end the run.

## Hard stops (never decide these alone)
- Touching a file outside the slice's Scope list (exception: the run files below).
- A new dependency, config file, network call, or contract enum value.
- Changing `defaults/` seed files, `contract/`, the event format, or a
  public function signature the slice fixes.
- A failing test in the existing suite whose fix lies outside the slice.
- Behaviour a user would notice that the spec and slice don't settle.

## Limits
- Three attempts at the same failing test, then record it under *Blocked* and
  move on to the next item.
- After a slice is green or blocked, start the next one that can start.
- Never loop on the environment: if setup fails twice, report and stop.

## End of a slice, whatever happened
1. Write `docs/runs/<YYYY-MM-DD>-<slice>.md` from `docs/runs/_template.md`.
2. Tick finished acceptance items in the slice file. Set `status: done` when
   every acceptance item passes and `scripts/check.py` is green for this
   slice. Keep `in-progress` when partial. Set `blocked` when a hard stop
   remains, and do not start slices that `depends_on` it.
3. Commit the slice's work, including unfinished work.
4. Start the next slice that is `ready` and whose dependencies are `done`.

## Who owns which file
- Your slice's Scope list is yours. Other slices' files are not, unless your
  Scope names them (B1, B2 and some C slices do).
- Web: one route module per slice in `web/routes/`, templates in
  `web/templates/<area>/`, CSS in `web/static/css/<slice>-<area>.css`
  (loaded automatically). Link to another slice's page only behind
  `{% if has_route(request, "<name>") %}`.
- Human-owned (never edit): `services/bridge.py`, `services/bridge_fake.py`,
  `tests/v2/contract/`, `tests/v2/conftest.py`, `web/app.py`,
  `web/__main__.py`, `web/templates/base.html`, `web/static/app.css`,
  `web/static/vendor/`, `pyproject.toml`, seed files in `defaults/` that
  already exist, CI, `AGENTS.md`, `.cursor/`, `docs/decisions.md`.
  All needed dependencies are already in `pyproject.toml`.

## Files you may change besides the slice scope
- Your slice file (status, ticks, notes).
- `docs/runs/<date>-<slice>.md` (your report).
- `scripts/strict_paths.d/<slice>.txt` (the modules you created).
- `tests/v2/architecture/allowlists.py` and `tests/legacy_known_failures.txt`:
  **remove** entries your slice fixed. Never add.

You never edit `docs/decisions.md`, `AGENTS.md`, `.cursor/`, CI or another
slice's files. Proposals for those go into your run report.

## Never
- Push, open pull requests, or merge unless the human asks.
- Delete, skip, xfail or loosen a test to make the suite pass.
- Call `jj` outside `persistence/vcs.py`, write a log line outside
  `services/event_log.py`, or make a remote call that bypasses `services/egress.py`.
- Write to, move or rename a user source file except through an accepted proposal.
- Add Node, npm, TypeScript, a bundler, a CSS framework or a frontend framework.
- Write a `.gitignore` or any file into a user's project outside `.iterthink/` and `.jj/`.
- Use Git or jj words in UI text (commit, branch, rebase, bookmark, repository).
- Call Ollama, a cloud model or any non-loopback address from tests.

## Commands
```
scripts/setup-agent-env.sh                 # fresh environment
uv run python scripts/check.py             # fast: lint, types, boundaries, unit tests
uv run python scripts/check.py --full      # everything incl. jj, integration, coverage
uv run pytest tests/v2 -k <name> -x        # one test while iterating
```

## Known traps (from earlier sessions)
- Exporting to DOCX/XLSX where CSV or Markdown is the working format.
- Proposing a TypeScript or framework frontend instead of Jinja + HTMX.
- Storing state in SQLite that is not rebuildable from files.
- Resolving a conflict automatically instead of showing it in review.
- Calling the hash-chained log "tamper-proof". It is tamper-evident.
- Mocking jj in integration tests. Use the real binary (`jj_bin` fixture).
