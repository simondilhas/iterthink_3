```
id: A2
status: ready
depends_on: []
```
# A2 · Event log with hash chain

**Goal:** decisions are appended to a per-machine, tamper-evident log that
anyone can verify with the standard library, and machine logs anchor each
other through checkpoints.

**Spec sections:** Storage: files are the truth; the event JSON example;
Audit trail (Seal, Verification); article §9.

## Scope
- `iterthink/services/event_log.py`, `iterthink/services/verify_log.py`
- `tests/v2/services/test_event_log.py`, `test_verify_log.py`,
  `tests/v2/invariants/test_hash_chain.py`
- `scripts/strict_paths.d/A2.txt`

## Out of scope
- Index (C1). Verify on open, audit export, handover (C13). Bridge wiring (B1).

## Interface
```python
@dataclass(frozen=True)
class Event:
    seq: int; ts: str; machine: str; actor: str; type: str
    project: str; payload: dict[str, Any]; contract: str
    prev_hash: str; hash: str

class LogCorrupt(Exception): ...

def append(project_dir: Path, *, machine: str, actor: str, type: str,
           project: str, payload: dict[str, Any], contract: str,
           now: Callable[[], datetime] = utc_now) -> Event: ...
def store_blob(project_dir: Path, text: str) -> str: ...          # "blob:<sha256>"
def read_blob(project_dir: Path, ref: str) -> str: ...
def read(log_path: Path) -> Iterator[Event]: ...                  # raises LogCorrupt
def read_all(project_dir: Path) -> list[Event]: ...               # all machines, sorted (ts, machine, seq)
def checkpoint(project_dir: Path, *, machine: str, actor: str, project: str,
               contract: str, now: Callable[[], datetime] = utc_now) -> Event: ...
CHECKPOINT_EVERY = 100
# verify_log.py — standard library only
def verify(log_path: Path) -> VerifyResult: ...   # ok, lines, error_line, reason
def verify_all(project_dir: Path) -> VerifyResult: ...  # every chain + checkpoints
def main(argv: list[str]) -> int: ...
```

## Decided for you
- Path `<project>/.iterthink/log/<machine>.jsonl`, parents created.
- Canonical JSON: `json.dumps(obj, sort_keys=True, separators=(",", ":"),
  ensure_ascii=False)`, UTF-8, one line, `\n`.
- `hash` = sha256 hex of canonical JSON of the event without `hash`.
  First `prev_hash` = 64 zeros. `seq` from 1 per machine log.
- `ts` UTC `YYYY-MM-DDTHH:MM:SSZ` from the injected `now`. Event id = `hash`.
- Write with `os.O_APPEND | os.O_CREAT | os.O_WRONLY`, one `os.write`, `os.fsync`.
  Thread lock per log path; multi-process writers are out of scope.
- Incomplete last line (no `\n`) → `append` raises `LogCorrupt`; never repair.
- Blobs `<project>/.iterthink/blobs/<sha256>`, temp file + `os.replace`.
- Payload: str, int, bool, None, list, dict. Floats raise `ValueError`.
- `verify_log.py` imports nothing from `iterthink`.
- Checkpoint: event type `checkpoint`, payload `{"heads": {<machine>: {"seq", "hash"}}}`
  with the last line of every *other* machine log present in `log/`.
  `append` writes one automatically after every `CHECKPOINT_EVERY`-th event of
  its own log; B1 also calls `checkpoint` when a project is closed.
  A machine log that ends mid-line is skipped in `heads` (not repaired).
- `verify` checks one chain. Cross-log checks (a checkpoint names a hash
  that no longer exists in the other log) are `verify_all(project_dir)` in
  `verify_log.py`, still standard library only.

## Acceptance
- [ ] `test_append_writes_one_canonical_line`
- [ ] `test_seq_increments_per_machine_log`
- [ ] `test_prev_hash_links_to_previous_line`, `test_first_prev_hash_is_zeros`
- [ ] `test_store_blob_is_content_addressed`
- [ ] `test_only_own_machine_log_is_written`
- [ ] `test_read_all_merges_machines_in_order`
- [ ] `test_float_in_payload_raises`
- [ ] `test_append_after_incomplete_last_line_raises`
- [ ] `test_verify_detects_edit` / `_removed_line` / `_reordered_lines` /
      `_incomplete_last_line`, each with the right `error_line`
- [ ] property: `test_any_single_byte_change_breaks_verification`
- [ ] property: `test_untouched_log_always_verifies`
- [ ] `test_verify_script_runs_with_stdlib_only` — `python -I verify_log.py`, empty PYTHONPATH
- [ ] `test_checkpoint_every_100_events_records_other_heads`
- [ ] `test_verify_all_detects_edit_in_other_log_via_checkpoint`
- [ ] `test_source_files_untouched`
