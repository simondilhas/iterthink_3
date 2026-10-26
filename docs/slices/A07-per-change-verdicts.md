```
id: A7
status: done
depends_on: [A5, B1]
```
# A7 · Per-change verdicts

**Goal:** in review, accept, reject or edit one paragraph of a proposal
without deciding the whole proposal.

**Spec sections:** Review screen (change fragments, `data-hash`, 409);
Principles (track decisions).

## Scope
- `iterthink/compare/engine_text.py` — a change id on every non-stable `Block`
- `iterthink/services/change_verdicts.py` — new: `ChangeVerdictsBridge` mixin
  (`decide_change`, `edit_change`), rebuild of the file from decided changes
- `iterthink/services/proposals.py` — fold `change_verdict` and `change_edit`
  events into `ProposalInfo.changes` and `candidate`
- `iterthink/services/bridge_real.py` — mix in `ChangeVerdictsBridge`
- `iterthink/services/bridge_fake.py` — the same behaviour in memory
- `tests/v2/contract/test_bridge_contract.py` — the contract tests below
- `iterthink/web/routes/review.py`, `templates/review/` — per-change actions
- `tests/v2/services/test_change_verdicts.py`, `tests/v2/web/test_a7_changes.py`
- `tests/v2/golden/diffs/doors.json` — ids appear in the golden diff
- `scripts/strict_paths.d/A7.txt`

## Out of scope
- Per-change verdicts on tables, plans and models: their changes keep `id=""`
  and are decided with the whole proposal. A later slice gives `CellChange` ids.
- Accept all / Reject all: they stay `accept` / `reject`.

## Interface
Contract (already in `services/bridge.py`):
```python
def decide_change(self, project, proposal_id, change_id, verdict, actor,
                  reason="", candidate=None) -> ProposalInfo: ...
def edit_change(self, project, proposal_id, change_id, text, actor,
                candidate=None) -> ProposalInfo: ...
# Block.id, ProposalInfo.changes (change id -> open|accepted|rejected),
# ProposalInfo.candidate
```

## Decided for you
- Change id: first 12 hex characters of sha256 over
  `path + "\0" + before + "\0" + after` of the block. Stable blocks get `""`.
- `candidate`: sha256 over the sorted `(path, proposed bytes)` pairs of the
  proposal's current draft. An edit makes a new draft, so the hash changes.
- `candidate` given and different from the current hash → `Conflict`, nothing
  is decided (the route answers 409 with the refreshed fragment marked outdated).
- Events: `change_verdict` `{proposal, change, verdict, reason}` (reason as a
  blob) and `change_edit` `{proposal, change, draft}`. Both rebuild from the log.
- Rejecting one change needs no reason; rejecting the last open change with
  none accepted rejects the proposal and needs a reason (`Invalid` otherwise).
- When the last open change is decided and at least one was accepted, the file
  is rebuilt: accepted changes take `after`, rejected ones `before`, stable
  blocks stay, paragraphs joined with a blank line, trailing newline kept as in
  the proposed text. Then it goes through the same path as `accept` (stale
  baseline → `conflict`, verdict event with `partial: true` when anything was
  rejected). Source files stay untouched until then.
- Unknown change id → `NotFound`. A decided proposal → `Conflict`.
- Routes: `POST /p/{id}/proposals/{pid}/changes/{cid}/accept|reject|edit`,
  form field `candidate`; response is the fragment plus an out-of-band status bar.

## Acceptance (tests first)
- [x] `test_text_blocks_carry_stable_change_ids` — same input, same ids; stable blocks `""`
- [x] contract: `test_deciding_every_change_applies_only_accepted_ones`
- [x] contract: `test_stale_candidate_is_a_conflict_and_decides_nothing`
- [x] contract: `test_rejecting_all_changes_rejects_the_proposal_with_reason`
- [x] contract: `test_edit_change_keeps_it_open_and_changes_the_candidate`
- [x] contract: `test_source_untouched_until_the_last_change_is_decided` (invariant 3)
- [x] `test_change_verdicts_rebuild_from_the_log` (invariant 5)
- [x] `test_change_fragment_posts_and_409_marks_outdated`

## Done when
All acceptance tests pass and `scripts/check.py --full` is green.
