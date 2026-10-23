```
id: C7
status: ready
depends_on: [B1, C15]
```
# C7 · Rules and automatic verdicts

**Goal:** you can allow narrow, deterministic kinds of change in advance or
refuse some paths outright; allowed changes apply on their own, are logged as
"auto · rule <id>" and can be undone in one step.

**Spec sections:** Agent rules (full); Principles (Track decisions);
Repository layout (`services/agent_rules.py`); article §4.

## Scope
- `iterthink/services/agent_rules.py`, `iterthink/compare/change_classes.py`
- `bridge_real.propose` — check rules before and after creating a proposal
- `iterthink/web/templates/review/` — "auto" badge and "Undo" (A5 owns the
  folder; add new partials only)
- `defaults/rules.yaml` (**new seed file**)
- `tests/v2/services/test_agent_rules.py`, `tests/v2/invariants/test_auto_verdicts.py`
- `scripts/strict_paths.d/C7.txt`

## Out of scope
- The settings page for rules (C15 shows inherited values). Agent profiles (C8).

## Interface
```python
@dataclass(frozen=True)
class Rules:
    default: Literal["propose", "direct", "deny"]
    direct: tuple[str, ...]          # "<glob>:<class>"
    deny: tuple[str, ...]            # globs
    propose_always: tuple[str, ...]  # globs
    deletions: Literal["propose", "deny"]

def load(project_dir: Path) -> Rules: ...                       # inherited via C15 settings
def decide(rules: Rules, actor: str, path: str, change: FileDiff,
           is_deletion: bool) -> Decision: ...                   # propose | direct(rule_id) | deny
CHANGE_CLASSES: tuple[str, ...]
def classify(path: str, before: bytes, after: bytes) -> frozenset[str]: ...
```

## Decided for you
- File and schema as in the spec: `.iterthink/settings/rules.yaml` (the spec's
  folder model puts rules under `settings/`; its Agent rules section says
  `.iterthink/rules.yaml` — use `settings/` so inheritance works like every
  other setting, and record this as a provisional decision):
  ```yaml
  agents:
    default: propose
    direct: ["**/*.md:typos"]
    deny: ["contracts/**"]
    propose_always: ["**/*.ifc", "**/*.csv"]
  deletions: propose
  ```
- Seed `defaults/rules.yaml`: `default: propose`, empty `direct` and `deny`,
  the spec's `propose_always`, `deletions: propose`.
- Applies to actors `agent:*`, `app:*`, `ai:*`. Never to `user:*` (D-011).
- Change classes, detected without AI: `whitespace`, `spelling` (pyspellchecker
  with the existing dictionaries in `persistence/spell_resources.py`,
  single-word replacements within edit distance 2), `typography` (quotes,
  dashes), `csv_format` (same cells, different quoting). `typos` =
  `whitespace` ∪ `spelling` ∪ `typography`. Nothing an LLM decides.
- Rule id = the matching entry as written (`**/*.md:typos`); shown as
  "auto · rule **/*.md:typos".
- Order: `deny` → refused with `Forbidden`, a `rule_denied` event, no proposal.
  Deletion and `deletions: deny` → same. Then `propose_always`, deletions, IFC
  (`.ifc`) and plans (`.pdf`) → always a proposal, whatever `direct` says.
  Then `direct`: a proposal whose every change on every file falls in the
  entry's class is accepted with actor `rule:<id>`, event `verdict` with
  `auto: true`. Everything else waits for a human.
- `default: direct` is refused at load (`Invalid`): `direct` is never the default.
- "Undo" on an auto verdict = `restore` of the version before it, logged by the user.

## Acceptance
- [ ] `test_spelling_fix_auto_accepted_under_rule`
- [ ] `test_mixed_change_waits_for_human`
- [ ] `test_rule_limited_to_paths`
- [ ] `test_deny_refuses_and_logs_without_proposal`
- [ ] `test_direct_never_applies_to_deletions_ifc_plans_or_propose_always` (parametrised)
- [ ] `test_default_direct_is_refused`
- [ ] `test_user_saves_are_never_ruled`
- [ ] `test_workspace_rules_inherited_by_project`
- [ ] `test_auto_verdict_logged_with_rule_id_and_undo_restores`
- [ ] property: `test_auto_never_applies_non_deterministic_classes`
