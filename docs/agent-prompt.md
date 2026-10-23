# Prompt for the build

Paste into the agent. It builds iterthink 2.0 until no slice can start.

---

Rewrite iterthink as 2.0, following `AGENTS.md` and `.cursor/rules/iterthink-2.mdc`.

Flet is removed when its replacement exists (slice C18). The Python core stays.
Version history is content-addressed snapshots in `.iterthink/versions/`
(slice A3). jj and connectors are not part of this version (C20 is dropped).

Start at the lowest-id slice in `docs/slices/` with `status: ready` whose
`depends_on` are `done`. Nobody will answer questions. Use the slice's
"Decided for you". Where the slice disagrees with the spec, follow the spec,
record it, and continue.

The bridge contract (`iterthink/services/bridge.py`, `bridge_fake.py`,
`tests/v2/contract/`) and the web skeleton are human-owned: build against
them, never change them.

When a slice is done or blocked, write `docs/runs/<date>-<slice>.md`, commit,
and start the next slice that can start. Stop when none can.

---

## Reviewer prompt (a fresh session, when a human asks)

Review the work for slice **<ID>** using `.cursor/commands/review-slice.md`.
You did not write this code. Output blocking issues, then non-blocking, each
with file:line.
