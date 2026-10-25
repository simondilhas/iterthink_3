```
id: C20
status: dropped
depends_on: [C2, C6, C15]
```
# C20 · bexio connector

Dropped on 2026-10-25: connectors are not part of this version.

**Goal:** accounting data from bexio is readable where the work happens
(apps, search, the line), without moving into project files.

**Spec sections:** article §8 (systems of record open up through APIs);
Principles (Egress); Privacy model.

**Set `ready`** by the human on 2026-10-23: bexio is normal API access, an
outbound HTTPS read that goes through egress like every other remote call. It
is not a new kind of component. The spec has no connector section yet: propose
its text in the run report.

## Scope
- `iterthink/services/bexio.py` — read-only client; builds requests, parses
  JSON, caches. It does not import `httpx`.
- `iterthink/services/egress.py` — add purpose `"api"` and
  `fetch(project_dir, url, *, headers, purpose="api") -> bytes`, the only place
  the HTTP request is made (keeps `test_remote_clients_only_in_ai_and_egress` green)
- Read functions for apps through C6's app bridge
- `tests/v2/services/test_bexio.py` (recorded fixtures, no live calls)
- `scripts/strict_paths.d/C20.txt`

## Decided for you
- Read-only: projects, contacts, invoices, timesheets. No writes to bexio.
- Host `https://api.bexio.com`, confirmed by the human. `httpx` and `keyring`
  are already dependencies; no new one.
- API token in the OS keyring, entered in settings (C15). Never in a file,
  an event or a log line.
- Every request goes through `egress.fetch` with purpose `"api"`, tier `cloud`:
  `none` → `EgressDenied`, no request; `shielded` and `allowed` → sent. Only
  the token and query parameters leave the machine, never project content.
- Each request writes an `egress` audit event (purpose, host, endpoint, count),
  never the response body.
- Data is fetched on demand and not stored in the project; cache in the
  machine state dir with a short TTL (module constant).

## Acceptance
- [ ] `test_reads_projects_and_invoices_from_fixtures`
- [ ] `test_token_from_keyring_only`
- [ ] `test_egress_none_blocks_requests`
- [ ] `test_nothing_written_to_project`
- [ ] `test_egress_fetch_writes_audit_event_without_body`
