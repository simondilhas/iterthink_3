# Decisions

Settled choices. Agents read this file but never edit it; they put new
questions in their run report. The human moves answers here (Accepted or
Rejected) with a date. Same rule as the product: AI proposes, a human gives
the verdict.

Format: `D-NNN · title · status · date` then 1–4 lines.

## Proposed
_(human copies open questions from run reports here while thinking them over)_

## Accepted

**D-001 · Plain HTML frontend · accepted · 2026-10-23**
Jinja2 + HTMX + vanilla JS custom elements with `// @ts-check`. No TypeScript
compile, no Node, no bundler, no framework. Trade-off accepted: less tooling,
more state on the server.

**D-002 · Open working formats · accepted · 2026-10-23**
Inside a project, working files are CSV, Markdown or JSON. DOCX, XLSX, PDF
only at the boundary: kept as received, or generated into `.iterthink/exports/`.
Plans stay PDF, models stay IFC. A tabular output defaults to CSV.

**D-004 · Files are the truth · accepted · 2026-10-23**
SQLite is a machine-local index rebuilt from logs, `.iterthink/versions/` and
files. No database on shared folders. Anything not rebuildable does not go
into SQLite.

**D-005 · Tamper-evident, not tamper-proof · accepted · 2026-10-23**
Per-machine hash-chained JSONL logs. Wording in code, UI and docs:
"tamper-evident". Protection against the owner needs an external anchor.

**D-006 · Source files are never moved · accepted · 2026-10-23**
iterthink writes a source file only on an accepted proposal. Its own data
lives in `<project>/.iterthink/`. No `.gitignore` in user folders.

**D-007 · AI waits for Enter · accepted · 2026-10-23**
No AI action while typing. Enter in the line, Mod+Enter in documents.
Keyword search may update live.

**D-008 · Conflicts are shown, never resolved silently · accepted · 2026-10-23**
Competing proposals and conflicting verdicts across machines surface in review.

**D-009 · Built with AI, tests first · accepted · 2026-10-23**
The agent builds the slices in `docs/slices/`, tests first, and writes a run
report for each. Allowlists in architecture tests only shrink. A human reads
the reports when they want to. Review does not gate the next slice.

**D-011 · A user's own save is their verdict · accepted · 2026-10-26**
Saving your own edit creates a version and logs it as your accepted change
(`kind: own_edit`). Only agents, apps and rules go through proposals. Affects A1, B1.

**D-012 · Human-owned bridge contract · accepted · 2026-10-26**
`services/bridge.py`, its fake and `tests/v2/contract/` are written by the
human; slices implement them. UI and MCP slices start on the fake, so all of
wave 1 runs in parallel. Affects every slice.

**D-013 · English UI text · accepted · 2026-10-26**
UI text in English, kept in templates, no translation system yet. Affects A1, A5.

**D-014 · Agents never decide · accepted · 2026-10-26**
MCP and the agent runner expose no accept, reject, save or restore. Affects A6, C8.

**D-015 · MCP reads content only under egress `allowed` until C2 · accepted · 2026-10-26**
`shielded` and `none` refuse content tools until C2 adds redacted reads for
`shielded`. Affects A6, C2.

**D-016 · One continuous run · accepted · 2026-10-23**
Flet is replaced by the local web UI in `docs/spec/`.
The agent keeps going through the slice order as far as it can. A blocked
slice does not stop slices that do not depend on it. Connectors (C20) are
out of this version.

**D-017 · Contract follows the spec · accepted · 2026-10-26**
Task statuses use the spec's eight words and the task tools are bridge methods.
`Mode` has `review`, `FileDiff.kind` has `image`, `search` takes `kind` and
`in_history`. Per-change verdicts are in the contract (slice A7). Apps stay on
`srcdoc`; `AppInfo.url` is None. Contract tests run against both bridges, no jj.

## Rejected

**D-003 · jj from day one · rejected · 2026-10-23**
Version history in this version is content-addressed snapshots in
`.iterthink/versions/` (slice A3). jj stays under "Later" in the spec.

**D-010 · One slice, then wait for evening review · rejected · 2026-10-23**
Replaced by D-016. The build is not cut into days.
