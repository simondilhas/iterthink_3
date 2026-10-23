"""Known violations of architecture rules, as of the baseline (slice A0).

RULES FOR THIS FILE
- Entries may only be removed. Adding one needs a human decision in
  docs/decisions.md; agents never add entries.
- Each entry names the slice that removes it.
- A stale entry (no longer violating) fails `test_allowlist_entries_are_still_needed`,
  so the list shrinks as soon as the fix lands.

Paths are relative to the repo root. A trailing "/" covers a whole directory.
"""

from __future__ import annotations

# This tree has no Flet. Entries below stay empty unless a slice records one.
FLET_IMPORTS: dict[str, str] = {}

# Core modules importing UI packages (web, mcp, desktop).
CORE_IMPORTS_UI: dict[str, str] = {}

# Modules other than ai/ and services/egress.py importing HTTP / LLM clients.
REMOTE_CLIENT_IMPORTS: dict[str, str] = {
    "iterthink/licensing.py": "C2",
    "iterthink/services/remote_model_list.py": "C2",
    "iterthink/services/yourcompanyos_client.py": "C2",
}

# Modules other than services/event_log.py opening files in append mode.
APPEND_MODE_WRITES: dict[str, str] = {}

# Modules mentioning ".gitignore" (reading one to skip files may be legitimate
# legacy behaviour; writing one never is, see D-006).
GITIGNORE_REFS: dict[str, str] = {}
