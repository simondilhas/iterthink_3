```
id: C3
status: ready
depends_on: [C1, C2, C4]
```
# C3 · The line and intent

**Goal:** one line starts any task: on Enter iterthink opens the surface it
understood, says so in one quiet line, and lets you switch.

**Spec sections:** The line (Core rule, First Enter decides the mode, Enter by
mode, Recall and state); Search → Where search lives; Repository layout →
`services/intent.py`; article §5.

## Scope
- `iterthink/services/intent.py`, `bridge_real.interpret`
- `iterthink/web/routes/line.py` (takes over `POST /p/{id}/line` from A1)
- `iterthink/web/templates/line/`, `static/js/the-line.js`, `static/css/c3-line.css`
- `tests/v2/services/test_intent.py`, `tests/v2/web/test_c3_line.py`
- `scripts/strict_paths.d/C3.txt`

Not in scope: `bridge_fake.py` is human-owned. Record the fake behaviour the
web tests need in the run report; test the routes against `RealBridge` with a
fake router.

## Out of scope
- The surfaces themselves: document (C4), chat (C5), app (C6), task board (C8).
- Voice (C16).

## Interface
```python
@dataclass(frozen=True)
class LineContext:
    project: str
    open_path: str | None      # the document the line was recalled from, if any
    recent_paths: tuple[str, ...]

@dataclass(frozen=True)
class Classified:
    intent: Intent             # bridge type: mode, title, plan
    confidence: float          # 0..1
    alternatives: tuple[Mode, ...]
    via: Literal["rule", "model"]

def interpret(project_dir: Path, line: str, context: LineContext, router: Router) -> Classified: ...
```
`bridge_real.interpret(project, line)` calls it and returns `.intent`.

## Decided for you
- While typing: keyword search only (A1). The AI never runs before Enter.
- Enter (and Mod+Enter, which is the same in the line) → `interpret` → the
  most likely surface opens directly, empty or with the answer, per the spec's
  table. Above it one quiet line: "Opened as document · switch", where
  *switch* lists `alternatives`. Switching reopens the same line in the other
  mode; nothing is lost.
- The surface is built, not filled: a new document gets its title and no AI
  text; a task creates task files in Backlog only (C8); nothing runs that the
  user did not ask for.
- Modes (contract `Mode`): `search` ("find / where / which document" → results
  surface with hybrid search, C1), `document` (C4: asks file name and folder,
  suggested from the title), `chat` (C5), `app` (C6), `task` (C8).
  A mode whose route does not exist yet shows "coming soon" and falls back to search.
- `review` ("Compare spec v6 and v7", a dropped file) is in the spec but not in
  the contract's `Mode`. Detect it in `intent.py` (internal), route it to A5's
  version / diff page, and record under Blocked that `Intent.mode` cannot carry
  it through the bridge yet.
- Rules first (deterministic: "new document …", "neues Dokument …", "schedule",
  "Liste", "?" at the end, "compare … and …", "vergleiche"), local model
  second via `llm_router` with `egress.check(..., "chat", tier)`. Below
  confidence 0.6 the quiet line also says "not sure".
- Every classification is an audit event `intent` (model, prompt id, mode,
  confidence; the line text as a blob); a switch is logged as the user's
  correction on that event.
- The intent prompt belongs in `defaults/prompts.yaml`, an existing seed file:
  do not edit it. Put the proposed text in the run report and use a module
  constant until a human adds it.
- Recall: Mod+K brings the line back from any surface, scoped (in a document
  it acts on that document; on the start screen on the project). `/` at the
  start of an empty paragraph does the same in C4's editor (C4 dispatches an
  `it-recall` event; this slice handles it).
- The dot: steady = idle, pulsing = open proposals exist; clicking it opens
  A5's panel on the Proposals tab.
- Typing a project name, a file name or "continue" and pressing Enter reopens
  that work (rule, no model).
- Shift+Enter is a line break.

## Acceptance
- [ ] `test_typing_never_calls_the_model` — router fake records zero calls during search requests
- [ ] `test_enter_opens_surface_with_quiet_switch_line`
- [ ] `test_switch_reopens_line_in_other_mode_and_logs_correction`
- [ ] `test_mod_enter_is_same_as_enter_in_line`
- [ ] `test_rule_based_modes` (parametrised examples in German and English)
- [ ] `test_review_intent_routes_to_version_diff`
- [ ] `test_model_fallback_respects_egress_none`
- [ ] `test_unbuilt_mode_falls_back_to_search`
- [ ] `test_intent_is_logged_with_prompt_id`
- [ ] `test_continue_and_file_name_reopen_work`
- [ ] `test_dot_pulses_when_proposals_are_open`
