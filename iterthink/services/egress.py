"""One project setting decides whether content may leave the machine."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from iterthink.privacy_shield_settings import regex_redact_configured
from iterthink.services.event_log import append
from iterthink.services.projects import project_file, settings_of, write_yaml
from iterthink.services.proposals import CONTRACT

Purpose = Literal["agent", "app_build", "app_ai", "chat", "impact", "mcp"]
Tier = Literal["local", "company", "cloud"]
Decision = Literal["send", "shield", "deny"]
Emit = Callable[[Path, str, str, str, dict[str, object]], None]
_PURPOSES = {"agent", "app_build", "app_ai", "chat", "impact", "mcp"}
_TIERS = {"local", "company", "cloud"}


class EgressDenied(Exception):
    """A company or cloud call is not allowed for this project."""


@dataclass(frozen=True)
class ShieldedText:
    """Text after the egress decision, plus the placeholders to put back."""

    text: str
    placeholders: dict[str, str]
    decision: Decision


def check(project_dir: Path, purpose: Purpose, tier: Tier) -> Decision:
    """`send` as-is, `shield` through pattern redaction, or `deny`.

    `none` denies every company and cloud purpose, including `app_build`.
    `shielded` removes regex categories only (email, phone, keys, and similar).
    Names, addresses, organisations and project names stay in the text.
    """
    mode = _mode(project_dir)
    if tier == "local":
        return "send"
    if mode == "none":
        return "deny"
    if mode == "allowed":
        return "send"
    return "shield"


def prepare(project_dir: Path, text: str, purpose: Purpose, tier: Tier) -> ShieldedText:
    """Redact when the setting says so. A denial is recorded and raised."""
    decision = check(project_dir, purpose, tier)
    if decision == "deny":
        _audit(project_dir, purpose, tier, "deny", 0)
        raise EgressDenied(f"egress blocks {purpose} on {tier}")
    if decision == "send":
        return ShieldedText(text, {}, "send")
    redacted, mapping = regex_redact_configured(text, tier=tier)
    _audit(project_dir, purpose, tier, "shield", len(mapping))
    return ShieldedText(redacted, mapping, "shield")


def restore(shielded: ShieldedText, answer: str) -> str:
    """Put the redacted values back into an answer."""
    out = answer
    pairs = sorted(shielded.placeholders.items(), key=lambda item: len(item[0]), reverse=True)
    for placeholder, value in pairs:
        out = out.replace(placeholder, value)
    return out


def deliver(
    project_dir: Path,
    purpose: str,
    tier: str,
    text: str,
    send: Callable[[str], str],
) -> str:
    """Prepare, hand the text to `send`, and restore the answer."""
    prepared = prepare(project_dir, text, _purpose(purpose), _tier(tier))
    return restore(prepared, send(prepared.text))


def release(
    project_dir: Path,
    messages: list[dict[str, str]],
    purpose: str,
    tier: str,
) -> tuple[list[dict[str, str]], bool]:
    """Messages safe to send. The bool means they go out unchanged."""
    kind, level = _purpose(purpose), _tier(tier)
    decision = check(project_dir, kind, level)
    if decision == "deny":
        prepare(project_dir, "", kind, level)
        raise EgressDenied(f"egress blocks {purpose} on {tier}")
    if decision == "send":
        return messages, True
    outgoing: list[dict[str, str]] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str) and content:
            shielded = prepare(project_dir, content, kind, level)
            outgoing.append({**message, "content": shielded.text})
        else:
            outgoing.append(dict(message))
    return outgoing, False


def shield_text(root: Path, text: str, purpose: str = "mcp") -> str:
    """Redact one string leaving through MCP."""
    return prepare(root, text, _purpose(purpose), "cloud").text


def apply_setting(root: Path, project: str, value: str, actor: str, emit: Emit) -> None:
    """Store the egress setting and record the old and new values."""
    data = settings_of(root)
    previous = data.get("egress", "shielded")
    old = previous if isinstance(previous, str) else "shielded"
    data["egress"] = value
    write_yaml(project_file(root), data)
    emit(root, project, actor, "settings", {"egress": value, "old": old, "new": value})


def _purpose(value: str) -> Purpose:
    if value in _PURPOSES:
        return cast(Purpose, value)
    return "chat"


def _tier(value: str) -> Tier:
    if value in _TIERS:
        return cast(Tier, value)
    return "cloud"


def _mode(project_dir: Path) -> str:
    found = settings_of(project_dir).get("egress", "shielded")
    if found in {"none", "shielded", "allowed"}:
        return str(found)
    return "shielded"


def _project_id(project_dir: Path) -> str:
    found = settings_of(project_dir).get("id")
    return found if isinstance(found, str) else ""


def _machine(project_dir: Path) -> str:
    log = project_dir / ".iterthink" / "log"
    if not log.is_dir():
        return "m-local"
    names = sorted(path.stem for path in log.glob("*.jsonl"))
    return names[0] if names else "m-local"


def _audit(project_dir: Path, purpose: str, tier: str, decision: str, count: int) -> None:
    payload: dict[str, object] = {
        "purpose": purpose,
        "tier": tier,
        "decision": decision,
        "count": count,
    }
    append(
        project_dir,
        machine=_machine(project_dir),
        actor="user:local",
        type="egress",
        project=_project_id(project_dir),
        payload=payload,
        contract=CONTRACT,
    )
