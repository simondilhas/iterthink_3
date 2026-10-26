"""Counters of the model diffs run in this process, keyed by the pair's content."""

from __future__ import annotations

import hashlib
import threading

ENGINE_VERSION = "1"
_LOCK = threading.Lock()
_RUNS: dict[str, dict[str, int]] = {}
_NAMES = ("elements", "matched", "reshaped", "booleans", "fallbacks", "done")


def key_of(before: bytes | None, after: bytes | None) -> str:
    """Content key of a pair of model versions. Also names the GLB cache folder."""
    digest = hashlib.sha256()
    digest.update(ENGINE_VERSION.encode("utf-8"))
    digest.update(b"\0")
    digest.update(before or b"")
    digest.update(b"\0")
    digest.update(after or b"")
    return digest.hexdigest()


def start(key: str) -> None:
    with _LOCK:
        _RUNS[key] = dict.fromkeys(_NAMES, 0)


def set_count(key: str, name: str, value: int) -> None:
    with _LOCK:
        if key in _RUNS:
            _RUNS[key][name] = value


def bump(key: str, name: str) -> None:
    with _LOCK:
        if key in _RUNS:
            _RUNS[key][name] += 1


def counters(key: str) -> dict[str, int]:
    """A copy of the counters, or an empty mapping when no diff of the pair ran."""
    with _LOCK:
        return dict(_RUNS.get(key, {}))
