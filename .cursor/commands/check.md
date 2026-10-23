# Run checks and fix

Run `uv run python scripts/check.py`. For each failure: state the root cause
in one line, fix it inside the current slice's scope, rerun. Do not skip,
xfail or delete tests, and do not extend allowlists. If a fix needs a file
outside the slice, record it under Blocked in the run report and continue
with the remaining items.
