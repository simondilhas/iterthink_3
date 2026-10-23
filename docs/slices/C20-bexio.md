```
id: C20
status: dropped
depends_on: [C2]
```
# C20 · bexio connector

**Dropped for this version.** `.cursor/rules/iterthink-2.mdc` does not include connectors. Leave this slice. Do not start it.

**Goal:** accounting data from bexio is readable where the work happens
(apps, search, the line), without moving into project files.

**Spec sections:** article §8 (systems of record open up through APIs).

## Scope
- `iterthink/connectors/bexio.py` (read-only client), registered in the bridge
  as read functions for apps (C6)
- `tests/v2/connectors/test_bexio.py` (recorded fixtures, no live calls)
- `scripts/strict_paths.d/C20.txt`

## Decided for you
- Read-only: projects, contacts, invoices, timesheets. No writes to bexio.
- API token in the OS keyring, entered in settings (C15).
- Calls go through egress (`purpose="app_ai"` is not used; this is inbound
  data, but requests are still checked so `none` blocks network access).
- Data is fetched on demand and not stored in the project; cache in machine
  state dir with a short TTL.
- New dependency or remote host → this slice must be confirmed by you first
  (architecture test allowlists `connectors/` only after your decision).

## Acceptance
- [ ] `test_reads_projects_and_invoices_from_fixtures`
- [ ] `test_token_from_keyring_only`
- [ ] `test_egress_none_blocks_requests`
- [ ] `test_nothing_written_to_project`
