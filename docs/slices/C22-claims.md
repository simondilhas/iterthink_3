```
id: C22
status: done
depends_on: [B1]
```
# C22 · Claims

**Goal:** a chat, task or app file has one writer at a time, also across
machines on a shared folder; a second window sees it read-only with a banner.

**Spec sections:** Shared folders (network drives, NAS, synced folders) —
the claim bullet; Audit trail (claim takeover).

## Scope
- `iterthink/services/claims.py`
- `iterthink/web/templates/partials/claim_banner.html` (new partial)
- `tests/v2/services/test_claims.py`
- `scripts/strict_paths.d/C22.txt`

## Out of scope
- Using claims in chats (C5), tasks (C8), apps (C6). Log tailing (C14).
- Source files: they are never claimed; concurrent edits show as conflicts in review.

## Interface
```python
@dataclass(frozen=True)
class Claim:
    path: str; machine: str; user: str; since: str; heartbeat: str

class Claimed(Exception):
    holder: Claim

def acquire(project_dir: Path, path: str, *, machine: str, user: str,
            now: Callable[[], datetime] = utc_now) -> Claim: ...      # raises Claimed
def heartbeat(project_dir: Path, claim: Claim, now: ...) -> Claim: ...
def release(project_dir: Path, claim: Claim) -> None: ...
def holder(project_dir: Path, path: str, now: ...) -> Claim | None: ... # None if free or stale
def take_over(project_dir: Path, path: str, *, machine: str, user: str,
              actor: str, now: ...) -> Claim: ...                      # logs an audit event
HEARTBEAT_EVERY = timedelta(seconds=30)
STALE_AFTER = timedelta(minutes=2)
```

## Decided for you
- Claim file `<file>.claim` next to the claimed file (inside `.iterthink/`),
  created with `os.O_CREAT | os.O_EXCL`; JSON with machine, user, since, heartbeat.
- Heartbeat rewrites the claim (temp file + `os.replace`) every 30 s from a
  background thread owned by the caller.
- Stale = no heartbeat for 2 minutes. A stale claim is offered for takeover,
  never taken silently; `take_over` writes a `claim_takeover` event with the
  old holder.
- `release` deletes the claim only if it is still ours (same machine, same since).
- Paths must be under `.iterthink/chats/`, `.iterthink/tasks/` or
  `.iterthink/apps/`; anything else raises `ValueError`.

## Acceptance
- [x] `test_second_acquire_raises_claimed_with_holder`
- [x] `test_release_frees_and_only_own_claim_is_released`
- [x] `test_stale_claim_is_free_for_holder_check`
- [x] `test_take_over_logs_event_with_old_holder`
- [x] `test_claims_only_for_chat_task_app_files`
- [x] `test_two_bridges_one_folder_one_writer` — two machine ids, one project
