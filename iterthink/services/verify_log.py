"""Verify a hash-chained log with the standard library only.

Run as a script: ``python -I verify_log.py <log-or-project>``.
A project directory checks every machine log and every checkpoint.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

ZEROS = "0" * 64


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of checking one log or a whole project."""

    ok: bool
    lines: int
    error_line: int | None
    reason: str


def canonical_json(obj: object) -> str:
    """Sorted-key JSON, UTF-8, no spaces."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(obj: Mapping[str, Any]) -> str:
    """SHA-256 of the event without its own ``hash`` field."""
    body = {key: value for key, value in obj.items() if key != "hash"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _fail(lines: int, error_line: int | None, reason: str) -> VerifyResult:
    return VerifyResult(False, lines, error_line, reason)


def _split_lines(data: bytes) -> tuple[list[bytes], str | None]:
    """Split on ``\\n`` only. A missing final newline is an incomplete line."""
    if not data:
        return [], None
    if not data.endswith(b"\n"):
        return [], "incomplete line"
    parts = data.split(b"\n")[:-1]
    return parts, None


def _line_hash(text: str, index: int, prev: str) -> tuple[str | None, str | None]:
    """Return ``(hash, None)`` or ``(None, reason)`` for one complete line."""
    try:
        parsed: object = json.loads(text)
    except json.JSONDecodeError:
        return None, "invalid json"
    if not isinstance(parsed, dict):
        return None, "invalid json"
    obj = cast(dict[str, Any], parsed)
    digest = obj.get("hash")
    if not isinstance(digest, str) or digest != content_hash(obj):
        return None, "hash mismatch"
    if text != canonical_json(obj):
        return None, "not canonical"
    if obj.get("prev_hash") != prev:
        return None, "prev_hash mismatch"
    if obj.get("seq") != index:
        return None, "seq mismatch"
    return digest, None


def verify(log_path: Path) -> VerifyResult:
    """Check one machine log. ``error_line`` is 1-based."""
    if not log_path.is_file():
        return _fail(0, None, "log not found")
    data = log_path.read_bytes()
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return _fail(data.count(b"\n") + 1, 1, "invalid utf-8")
    lines, problem = _split_lines(data)
    if problem is not None:
        return _fail(data.count(b"\n") + 1, data.count(b"\n") + 1, problem)
    prev = ZEROS
    total = len(lines)
    for index, raw in enumerate(lines, start=1):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return _fail(total, index, "invalid utf-8")
        digest, reason = _line_hash(text, index, prev)
        if reason is not None or digest is None:
            return _fail(total, index, reason or "hash mismatch")
        prev = digest
    return VerifyResult(True, total, None, "")


def _objects(log_path: Path) -> list[dict[str, Any]]:
    data = log_path.read_bytes()
    lines, _problem = _split_lines(data)
    found: list[dict[str, Any]] = []
    for raw in lines:
        parsed: object = json.loads(raw.decode("utf-8"))
        found.append(cast(dict[str, Any], parsed))
    return found


def _checkpoint_break(
    events: list[dict[str, Any]], logs: dict[str, list[dict[str, Any]]]
) -> tuple[int, str] | None:
    for index, obj in enumerate(events, start=1):
        if obj.get("type") != "checkpoint":
            continue
        payload = obj.get("payload")
        heads = payload.get("heads") if isinstance(payload, dict) else None
        if not isinstance(heads, dict):
            return index, "checkpoint heads missing"
        for machine, head in heads.items():
            if not isinstance(machine, str) or not isinstance(head, dict):
                return index, "checkpoint head missing"
            digest = head.get("hash")
            other = logs.get(machine, [])
            if not any(event.get("hash") == digest for event in other):
                return index, "checkpoint head missing"
    return None


def verify_all(project_dir: Path) -> VerifyResult:
    """Every machine chain, then checkpoint heads still present in those logs."""
    log_dir = project_dir / ".iterthink" / "log"
    if not log_dir.is_dir():
        return VerifyResult(True, 0, None, "")
    files = sorted(path for path in log_dir.glob("*.jsonl") if path.is_file())
    logs: dict[str, list[dict[str, Any]]] = {}
    total = 0
    for path in files:
        result = verify(path)
        total += result.lines
        if not result.ok:
            return result
        logs[path.stem] = _objects(path)
    for events in logs.values():
        broken = _checkpoint_break(events, logs)
        if broken is not None:
            line, reason = broken
            return _fail(total, line, reason)
    return VerifyResult(True, total, None, "")


def main(argv: list[str]) -> int:
    """Exit 0 when the path verifies, 1 when it does not, 2 on usage."""
    if len(argv) != 2:
        print("usage: verify_log.py <log-or-project>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    result = verify_all(path) if path.is_dir() else verify(path)
    if not result.ok:
        where = "-" if result.error_line is None else str(result.error_line)
        print(f"{where}: {result.reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
