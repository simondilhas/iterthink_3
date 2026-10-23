```
id: C13
status: ready
depends_on: [B1]
```
# C13 · Handover and audit

**Goal:** iterthink checks the decision record every time a project opens, and
you can hand over a project — full or client version — with a record the
client can verify without iterthink.

**Spec sections:** Folder model → Handover; Audit trail (full);
Repository layout (`services/audit.py`); article §9.

## Scope
- `iterthink/services/audit.py`, `iterthink/services/handover.py`, `bridge_real.handover`
- `iterthink/web/routes/handover.py`, `templates/handover/`, and a banner
  partial `templates/project/_log_broken.html` (new file)
- `tests/v2/services/test_audit.py`, `test_handover.py`
- `scripts/strict_paths.d/C13.txt`

## Out of scope
- Writing checkpoints (A2, B1). Erase (C19). An external timestamp service:
  the spec does not have one; propose it in the run report if you think it is needed.

## Decided for you
- Verify on open: `audit.verify_project(project_dir)` runs
  `verify_log.verify_all` (every chain and every checkpoint) when a project is
  opened, in the background. Any break → a red banner on the project page
  ("The decision record has a break at <machine> line <n>") and an `audit`
  event. Never repaired.
- Full handover: copy of the project folder as is (including `.iterthink/`),
  plus the audit export.
- Client handover: source files, deliverables (`.iterthink/exports/`), and
  `verification/` with: head hashes of all machine logs, the latest snapshot
  id, a verdict summary (CSV: time, who, file, verdict, reason), the logs, and
  `verify_log.py`. Excludes chats, rejected proposals, prompts, agent
  transcripts, apps. A `handover` event records the head hashes.
- Audit export into `.iterthink/exports/audit-<date>/`: CSV + JSON of all
  events with blob texts resolved, `verify_log.py`, and a readable report
  (Markdown) of verdicts per file.
- Wording: "tamper-evident" (architecture test).

## Acceptance
- [ ] `test_break_found_on_open_shows_banner_and_logs`
- [ ] `test_client_handover_excludes_internal_material`
- [ ] `test_client_can_verify_with_stdlib_only` — run the bundled script in `-I` mode
- [ ] `test_tampered_bundle_fails_verification`
- [ ] `test_handover_event_records_head_hashes`
- [ ] `test_audit_export_resolves_blobs_and_writes_report`
