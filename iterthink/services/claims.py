"""One writer at a time for a chat, task or app file on a shared folder."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from iterthink.services.event_log import append, utc_now
from iterthink.services.projects import settings_of
from iterthink.services.proposals import CONTRACT

HEARTBEAT_EVERY = timedelta(seconds=30)
STALE_AFTER = timedelta(minutes=2)
_AREAS = frozenset({"chats", "tasks", "apps"})


@dataclass(frozen=True)
class Claim:
    """Who is writing one file, and when they last said so."""

    path: str
    machine: str
    user: str
    since: str
    heartbeat: str


class Claimed(Exception):
    """Someone else holds the file. `holder` is that claim, even when it is stale."""

    holder: Claim

    def __init__(self, holder: Claim) -> None:
        self.holder = holder
        super().__init__(f"{holder.user} holds {holder.path}")


def _check(path: str) -> str:
    if not path or "\\" in path or path.startswith("/") or ":" in path:
        raise ValueError(f"claim path must stay inside .iterthink: {path!r}")
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"claim path must stay inside .iterthink: {path!r}")
    if len(parts) < 3 or parts[0] != ".iterthink" or parts[1] not in _AREAS:
        raise ValueError(f"claims are for chats, tasks and apps: {path!r}")
    return path


def _stamp(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _moment(now: Callable[[], datetime]) -> datetime:
    moment = now()
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _file(project_dir: Path, path: str) -> Path:
    return project_dir / f"{_check(path)}.claim"


def _body(claim: Claim) -> bytes:
    payload = {
        "heartbeat": claim.heartbeat,
        "machine": claim.machine,
        "since": claim.since,
        "user": claim.user,
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"{text}\n".encode()


def _load(target: Path, path: str) -> Claim | None:
    if not target.is_file():
        return None
    raw: object = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    machine, user = raw.get("machine"), raw.get("user")
    since, beat = raw.get("since"), raw.get("heartbeat")
    if not all(isinstance(item, str) for item in (machine, user, since, beat)):
        return None
    return Claim(path, str(machine), str(user), str(since), str(beat))


def _ours(current: Claim, claim: Claim) -> bool:
    return current.machine == claim.machine and current.since == claim.since


def _stale(claim: Claim, moment: datetime) -> bool:
    beat = datetime.fromisoformat(claim.heartbeat.replace("Z", "+00:00"))
    return moment - beat >= STALE_AFTER


def _project_id(project_dir: Path) -> str:
    found = settings_of(project_dir).get("id")
    if isinstance(found, str) and found:
        return found
    return project_dir.name


def _replace(target: Path, claim: Claim) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{os.getpid()}.tmp"
    temporary.write_bytes(_body(claim))
    temporary.replace(target)


def _exclusive(target: Path, claim: Claim) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    descriptor = os.open(target, flags, 0o644)
    try:
        os.write(descriptor, _body(claim))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def acquire(
    project_dir: Path,
    path: str,
    *,
    machine: str,
    user: str,
    now: Callable[[], datetime] = utc_now,
) -> Claim:
    """Create the claim. A claim that already exists is never replaced here."""
    target = _file(project_dir, path)
    existing = _load(target, path)
    if existing is not None:
        raise Claimed(existing)
    stamp = _stamp(_moment(now))
    claim = Claim(path, machine, user, stamp, stamp)
    try:
        _exclusive(target, claim)
    except FileExistsError:
        raced = _load(target, path)
        raise Claimed(raced if raced is not None else claim) from None
    return claim


def heartbeat(
    project_dir: Path,
    claim: Claim,
    now: Callable[[], datetime] = utc_now,
) -> Claim:
    """Refresh our claim. The caller runs this every HEARTBEAT_EVERY."""
    target = _file(project_dir, claim.path)
    current = _load(target, claim.path)
    if current is None or not _ours(current, claim):
        raise Claimed(current if current is not None else claim)
    updated = Claim(claim.path, claim.machine, claim.user, claim.since, _stamp(_moment(now)))
    _replace(target, updated)
    return updated


def release(project_dir: Path, claim: Claim) -> None:
    """Delete the claim when it is still the one we acquired."""
    target = _file(project_dir, claim.path)
    current = _load(target, claim.path)
    if current is not None and _ours(current, claim):
        target.unlink()


def holder(
    project_dir: Path,
    path: str,
    now: Callable[[], datetime] = utc_now,
) -> Claim | None:
    """The live writer, or None when the file is free or the claim is stale."""
    found = _load(_file(project_dir, path), path)
    if found is None or _stale(found, _moment(now)):
        return None
    return found


def take_over(
    project_dir: Path,
    path: str,
    *,
    machine: str,
    user: str,
    actor: str,
    now: Callable[[], datetime] = utc_now,
) -> Claim:
    """Take a stale claim and record who held it. A live claim stays where it is."""
    target = _file(project_dir, path)
    current = _load(target, path)
    moment = _moment(now)
    if current is None:
        raise ValueError("no claim to take over")
    if not _stale(current, moment):
        raise Claimed(current)
    stamp = _stamp(moment)
    taken = Claim(path, machine, user, stamp, stamp)
    _replace(target, taken)
    append(
        project_dir,
        machine=machine,
        actor=actor,
        type="claim_takeover",
        project=_project_id(project_dir),
        payload={
            "machine": current.machine,
            "path": path,
            "since": current.since,
            "user": current.user,
        },
        contract=CONTRACT,
        now=now,
    )
    return taken
