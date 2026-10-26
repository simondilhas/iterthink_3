# Audit trail
- The event log is the audit trail. `content_changes` and `audit_events` in
  the index are projections of it for querying.
- Event types cover everything that happened: version created, change
  detected, verdict given, intent classified, app built / kept / discarded,
  export created, agent call, task transitions, rule applied, settings that
  affect AI, claim takeover.
- Every event has actor (`user:<name>` | `agent:<name>` | `app:<slug>` |
  `ai:<prompt id>` | `rule:<id>`), input source (`typed` | `voice` | `file`),
  model, prompt version, timestamp (UTC).
- Seal: each machine log is a hash chain (`hash` = SHA-256 over canonical
  JSON of the event incl. `prev_hash`). Every 100 events, or on close, a
  `checkpoint` event records the current head hashes of all other machine
  logs it has merged, so chains anchor each other and deleting or editing a
  line in any log is detectable.
- Verification: `services/audit.py` verifies all chains and checkpoints on
  open and warns on any break. Audit export writes a standalone verification
  script (stdlib Python only) and a readable report; anyone can verify the
  log without iterthink.
- Logs are never rewritten. Corrections are new events.

# Erase
- Personal data or a wrong upload can be erased from history. Snapshot objects
  that only the erased versions referenced are deleted. Blobs referenced only
  by events that name those versions are deleted too.
- The log is not rewritten. A new erase event records a hash of each file
  path, the version ids, who erased, and the reason. It does not record the
  content or the path.
- Erase removes history, not the working file on disk.
- Erase needs a reason and a second confirmation.
- Another machine drops the same bytes the next time it reads history.
- Checkpoints and handover bundles made before the erase still verify. The
  chain is unchanged. A bundle made before the erase still contains what it
  contained then.

# Security
- Bind 127.0.0.1 only. Token generated at startup, handed to the page through
  pywebview's JS API, required on every request including SSE.
- CSP for the app shell: same-origin scripts only, no inline scripts.
  Ad-hoc app frames have their own CSP (see Ad-hoc apps); never relax the
  shell's CSP for them.
- Validate every path stays inside the current project (or its workspace for
  workspace settings). Symlinks pointing outside are not followed.
- Secrets stay in the keyring-backed vault; never render them into HTML.
