"""Append-only, per-machine event log. The only writer of log lines."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from iterthink.services.verify_log import ZEROS, canonical_json, content_hash, verify

CHECKPOINT_EVERY = 100

_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


class LogCorrupt(Exception):
    """A log line is incomplete or does not match its hash chain."""


@dataclass(frozen=True)
class Event:
    """One verified log line."""

    seq: int
    ts: str
    machine: str
    actor: str
    type: str
    project: str
    payload: dict[str, Any]
    contract: str
    prev_hash: str
    hash: str


def utc_now() -> datetime:
    """Current time in UTC."""
    return datetime.now(UTC)


def _format_ts(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def _log_path(project_dir: Path, machine: str) -> Path:
    if not machine or machine in {".", ".."} or "/" in machine or "\\" in machine:
        raise ValueError("machine must be a single path segment")
    return project_dir / ".iterthink" / "log" / f"{machine}.jsonl"


def _walk(value: object) -> None:
    if value is None or isinstance(value, str | bool):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        raise ValueError("payload must not contain floats")
    if isinstance(value, list):
        for item in value:
            _walk(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("payload keys must be strings")
            _walk(item)
        return
    raise ValueError("payload has an unsupported value")


def _require_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    _walk(payload)
    return dict(payload)


def _tail(path: Path) -> tuple[int, str]:
    if not path.exists() or path.stat().st_size == 0:
        return 0, ZEROS
    result = verify(path)
    if not result.ok:
        raise LogCorrupt(result.reason)
    last = path.read_bytes().split(b"\n")[-2]
    parsed: object = json.loads(last.decode("utf-8"))
    obj = cast(dict[str, Any], parsed)
    return int(obj["seq"]), str(obj["hash"])


def _event_from(obj: Mapping[str, Any]) -> Event:
    payload = obj["payload"]
    if not isinstance(payload, dict):
        raise LogCorrupt("payload must be an object")
    return Event(
        seq=int(obj["seq"]),
        ts=str(obj["ts"]),
        machine=str(obj["machine"]),
        actor=str(obj["actor"]),
        type=str(obj["type"]),
        project=str(obj["project"]),
        payload=cast(dict[str, Any], payload),
        contract=str(obj["contract"]),
        prev_hash=str(obj["prev_hash"]),
        hash=str(obj["hash"]),
    )


def _compose(
    *,
    seq: int,
    moment: datetime,
    machine: str,
    actor: str,
    type: str,
    project: str,
    payload: dict[str, Any],
    contract: str,
    prev_hash: str,
) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "actor": actor,
        "contract": contract,
        "machine": machine,
        "payload": payload,
        "prev_hash": prev_hash,
        "project": project,
        "seq": seq,
        "ts": _format_ts(moment),
        "type": type,
    }
    obj["hash"] = content_hash(obj)
    return obj


def _write_line(path: Path, obj: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (canonical_json(obj) + "\n").encode("utf-8")
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    fd = os.open(path, flags, 0o644)
    try:
        if os.write(fd, line) != len(line):
            raise OSError("short write")
        os.fsync(fd)
    finally:
        os.close(fd)


def _other_heads(project_dir: Path, own: str) -> dict[str, dict[str, Any]]:
    log_dir = project_dir / ".iterthink" / "log"
    heads: dict[str, dict[str, Any]] = {}
    if not log_dir.is_dir():
        return heads
    for path in sorted(log_dir.glob("*.jsonl")):
        if path.stem == own or not path.is_file():
            continue
        recorded = _head_of(path)
        if recorded is not None:
            heads[path.stem] = recorded
    return heads


def _head_of(path: Path) -> dict[str, Any] | None:
    data = path.read_bytes()
    if not data.endswith(b"\n"):
        return None
    try:
        parsed: object = json.loads(data.split(b"\n")[-2].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, IndexError):
        return None
    if not isinstance(parsed, dict):
        return None
    obj = cast(dict[str, Any], parsed)
    digest = obj.get("hash")
    seq = obj.get("seq")
    if not isinstance(digest, str) or not isinstance(seq, int) or isinstance(seq, bool):
        return None
    if content_hash(obj) != digest:
        return None
    return {"hash": digest, "seq": seq}


def _write_locked(
    path: Path,
    *,
    machine: str,
    actor: str,
    type: str,
    project: str,
    payload: dict[str, Any],
    contract: str,
    now: Callable[[], datetime],
) -> Event:
    seq, prev = _tail(path)
    obj = _compose(
        seq=seq + 1,
        moment=now(),
        machine=machine,
        actor=actor,
        type=type,
        project=project,
        payload=payload,
        contract=contract,
        prev_hash=prev,
    )
    _write_line(path, obj)
    return _event_from(obj)


def append(
    project_dir: Path,
    *,
    machine: str,
    actor: str,
    type: str,
    project: str,
    payload: dict[str, Any],
    contract: str,
    now: Callable[[], datetime] = utc_now,
) -> Event:
    """Append one event. Every 100th event of this log also writes a checkpoint."""
    body = _require_payload(payload)
    path = _log_path(project_dir, machine)
    with _lock_for(path):
        event = _write_locked(
            path,
            machine=machine,
            actor=actor,
            type=type,
            project=project,
            payload=body,
            contract=contract,
            now=now,
        )
        if type != "checkpoint" and event.seq % CHECKPOINT_EVERY == 0:
            _write_locked(
                path,
                machine=machine,
                actor=actor,
                type="checkpoint",
                project=project,
                payload={"heads": _other_heads(project_dir, machine)},
                contract=contract,
                now=now,
            )
        return event


def checkpoint(
    project_dir: Path,
    *,
    machine: str,
    actor: str,
    project: str,
    contract: str,
    now: Callable[[], datetime] = utc_now,
) -> Event:
    """Record the head hash of every other machine log."""
    path = _log_path(project_dir, machine)
    with _lock_for(path):
        return _write_locked(
            path,
            machine=machine,
            actor=actor,
            type="checkpoint",
            project=project,
            payload={"heads": _other_heads(project_dir, machine)},
            contract=contract,
            now=now,
        )


def store_blob(project_dir: Path, text: str) -> str:
    """Store ``text`` at ``.iterthink/blobs/<sha256>`` and return ``blob:<sha256>``."""
    data = text.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    directory = project_dir / ".iterthink" / "blobs"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / digest
    if not target.exists():
        temporary = directory / f".{digest}.{threading.get_ident()}.tmp"
        temporary.write_bytes(data)
        temporary.replace(target)
    return f"blob:{digest}"


def read_blob(project_dir: Path, ref: str) -> str:
    """Read a blob written by :func:`store_blob`."""
    prefix = "blob:"
    if not ref.startswith(prefix):
        raise ValueError("blob ref must be blob:<sha256>")
    path = project_dir / ".iterthink" / "blobs" / ref[len(prefix) :]
    return path.read_text(encoding="utf-8")


def read(log_path: Path) -> Iterator[Event]:
    """Yield every event. Raises :class:`LogCorrupt` when the chain does not verify."""
    if not log_path.exists():
        return iter(())
    result = verify(log_path)
    if not result.ok:
        raise LogCorrupt(result.reason)
    events: list[Event] = []
    for raw in log_path.read_bytes().split(b"\n")[:-1]:
        parsed: object = json.loads(raw.decode("utf-8"))
        events.append(_event_from(cast(dict[str, Any], parsed)))
    return iter(events)


def read_all(project_dir: Path) -> list[Event]:
    """Events from every machine log, ordered by time, machine, then sequence."""
    log_dir = project_dir / ".iterthink" / "log"
    if not log_dir.is_dir():
        return []
    events: list[Event] = []
    for path in sorted(log_dir.glob("*.jsonl")):
        if path.is_file():
            events.extend(read(path))
    events.sort(key=lambda event: (event.ts, event.machine, event.seq))
    return events
