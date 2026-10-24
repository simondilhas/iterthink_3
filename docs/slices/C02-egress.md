```
id: C2
status: done
depends_on: [B1]
```
# C2 · Egress and privacy shield

**Goal:** one project setting decides whether content may leave the machine,
and every path that could send content obeys it.

**Spec sections:** Principles (Egress); Privacy model (full spec); What stays → ai/
(privacy shield, llm_router); article §6.

## Scope
- `iterthink/services/egress.py`
- `iterthink/ai/llm_router.py` — every company/cloud call asks `egress` first
- `iterthink/mcp/server.py` — `shielded` returns redacted content instead of refusing
- `iterthink/services/bridge_real.py` — `set_egress` records old and new; `shield_text`
  is how MCP reaches the shield (a route and MCP cannot import `services.egress`)
- `iterthink/web/routes/settings.py` (egress switch only; the rest is C15)
- `iterthink/web/templates/settings/page.html`
- `tests/v2/services/test_egress.py`, `tests/v2/invariants/test_egress_none.py`
- `tests/v2/e2e/test_day_one.py` — the real-bridge read now expects redacted text
- `scripts/strict_paths.d/C2.txt`

## Interface
```python
class EgressDenied(Exception): ...
def check(project_dir: Path, purpose: Literal["agent", "app_build", "app_ai", "chat", "impact", "mcp"],
          tier: Literal["local", "company", "cloud"]) -> Literal["send", "shield", "deny"]: ...
def prepare(project_dir: Path, text: str, purpose: str, tier: str) -> ShieldedText: ...  # redacts, keeps placeholders
def restore(shielded: ShieldedText, answer: str) -> str: ...
```

## Decided for you
- `none`: only `local` tier allowed; any company/cloud call → `EgressDenied`.
- `shielded` (default): company/cloud calls go through the existing privacy
  shield (regex + local LLM redaction), placeholders re-injected on return.
- `allowed`: sent as is.
- `app_build` is the one exception: the builder receives structure, never
  content (spec Ad-hoc apps → Privacy model), so it may use company/cloud
  under every egress value. Under `none` and `shielded` its schemas still pass
  the shield. `app_ai` (AI blocks an app calls at runtime) follows the normal rules.
- Every denial and every shielded send writes an `egress` audit event with
  purpose, tier and counts (never the content). Changing the setting writes a
  `settings` event with old and new value.
- The architecture test `test_remote_clients_only_in_ai_and_egress` must stay green.

## Acceptance
- [x] `test_none_blocks_company_and_cloud_for_every_purpose_except_app_build` (parametrised)
- [x] `test_app_build_schemas_are_shielded_under_none_and_shielded`
- [x] `test_shielded_redacts_and_restores_placeholders`
- [x] `test_allowed_passes_text_unchanged`
- [x] property: `test_egress_none_attempts_no_remote_call` — fake router records calls
- [x] `test_mcp_shielded_returns_redacted_content`
- [x] `test_egress_changes_are_logged`
- [x] `test_settings_page_switches_egress`
