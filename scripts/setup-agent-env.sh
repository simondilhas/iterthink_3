#!/usr/bin/env bash
# Prepares a fresh Linux environment for an unattended agent run.
# Point your agent runner's setup/install step at this script.
# Idempotent: safe to run on every start.
set -euo pipefail

BIN="${HOME}/.local/bin"
mkdir -p "$BIN"
export PATH="$BIN:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

uv sync --all-extras

echo "uv:  $(uv --version)"
echo "Agent environment ready. Run: uv run python scripts/check.py"
