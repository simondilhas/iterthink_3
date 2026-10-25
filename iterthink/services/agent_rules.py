"""Rules the user set in advance. Agents, apps and the margin obey them."""

from __future__ import annotations

import fnmatch
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from iterthink.compare.change_classes import classify
from iterthink.persistence.snapshots import SnapshotError, Snapshots
from iterthink.services.bridge import (
    FileDiff,
    Forbidden,
    Invalid,
    NotFound,
    ProposalInfo,
    ProposalStatus,
    kind_of,
)
from iterthink.services.projects import inside, relative
from iterthink.services.proposals import create, reason_text
from iterthink.services.settings import load_yaml

_RULED = ("agent:", "app:", "ai:")
_FORCED = {".ifc", ".pdf"}
_GROUPS = {
    "whitespace": frozenset({"whitespace"}),
    "spelling": frozenset({"spelling"}),
    "typography": frozenset({"typography"}),
    "csv_format": frozenset({"csv_format"}),
    "typos": frozenset({"whitespace", "spelling", "typography"}),
}


class _Host(Protocol):
    machine: str

    def _root(self, project: str) -> Path: ...
    def _event(
        self, root: Path, project: str, actor: str, kind: str, payload: dict[str, object]
    ) -> None: ...

    _now: Callable[[], datetime]

    def accept(self, project: str, proposal_id: str, actor: str, reason: str = "") -> object: ...
    def proposals(
        self, project: str, status: ProposalStatus | None = None
    ) -> list[ProposalInfo]: ...


@dataclass(frozen=True)
class Rules:
    default: Literal["propose", "direct", "deny"]
    direct: tuple[str, ...]
    deny: tuple[str, ...]
    propose_always: tuple[str, ...]
    deletions: Literal["propose", "deny"]


@dataclass(frozen=True)
class Decision:
    action: Literal["propose", "direct", "deny"]
    rule_id: str = ""


def load(project_dir: Path) -> Rules:
    """Project rules, inherited like every other settings file."""
    data = load_yaml(project_dir, "rules.yaml")
    agents = data.get("agents")
    body = agents if isinstance(agents, dict) else {}
    default = body.get("default", data.get("default", "propose"))
    if default == "direct":
        raise Invalid("direct is never the default")
    chosen: Literal["propose", "deny"] = "deny" if default == "deny" else "propose"
    deletions = data.get("deletions", "propose")
    policy: Literal["propose", "deny"] = "deny" if deletions == "deny" else "propose"
    return Rules(
        default=chosen,
        direct=_strings(body.get("direct")),
        deny=_strings(body.get("deny")),
        propose_always=_strings(body.get("propose_always")),
        deletions=policy,
    )


def decide(rules: Rules, actor: str, path: str, change: FileDiff, is_deletion: bool) -> Decision:
    """propose, direct under one rule, or deny. A person is never ruled."""
    if not actor.startswith(_RULED):
        return Decision("propose")
    for glob in rules.deny:
        if _matches(glob, path):
            return Decision("deny", glob)
    if is_deletion and rules.deletions == "deny":
        return Decision("deny", "deletions")
    if is_deletion or _forced(rules, path):
        return Decision("propose")
    matched = _direct(rules, path, change)
    if matched is not None:
        return matched
    if rules.default == "deny":
        return Decision("deny", "default")
    return Decision("propose")


def verdict_for(root: Path, changes: Mapping[str, str], actor: str) -> Decision:
    """One decision for the whole proposal. Mixed files wait for a person."""
    if not actor.startswith(_RULED):
        return Decision("propose")
    rules = load(root)
    forced = False
    names: list[str] = []
    for path, text in changes.items():
        choice = _one(rules, root, actor, path, text)
        if choice.action == "deny":
            return choice
        if choice.action == "direct":
            names.append(choice.rule_id)
        else:
            forced = True
    if forced or len(set(names)) != 1:
        return Decision("propose")
    return Decision("direct", names[0])


def guarded_propose(
    host: _Host,
    project: str,
    changes: Mapping[str, str],
    actor: str,
    reason: str,
    baseline: str | None,
) -> ProposalInfo:
    """Create the proposal, refuse it, or accept it under a rule."""
    root = host._root(project)
    rels = {relative(path): text for path, text in changes.items()}
    for rel in rels:
        if kind_of(rel) not in {"markdown", "table", "text"}:
            raise Invalid(f"{rel} is not a text file")
        inside(root, rel)
    choice = verdict_for(root, rels, actor)
    if choice.action == "deny":
        host._event(
            root,
            project,
            actor,
            "rule_denied",
            {"paths": sorted(rels), "rule": choice.rule_id},
        )
        raise Forbidden(f"refused by rule {choice.rule_id}")
    made = _draft(host, root, project, rels, actor, reason, baseline)
    if choice.action != "direct":
        return made
    host.accept(project, made.id, f"rule:{choice.rule_id}", reason)
    return next(item for item in host.proposals(project, None) if item.id == made.id)


def _one(rules: Rules, root: Path, actor: str, path: str, text: str) -> Decision:
    before = _bytes(root, path)
    after = text.encode("utf-8")
    classes = classify(path, before, after)
    change = FileDiff(path, "text", "changed", details={"classes": sorted(classes)})
    return decide(rules, actor, path, change, _deletion(root, path, text))


def _draft(
    host: _Host,
    root: Path,
    project: str,
    rels: Mapping[str, str],
    actor: str,
    reason: str,
    baseline: str | None,
) -> ProposalInfo:
    try:
        made = create(
            root,
            Snapshots(root),
            machine=host.machine,
            project=project,
            changes=rels,
            actor=actor,
            reason=reason,
            baseline=baseline,
            now=host._now,
        )
    except SnapshotError as exc:
        raise NotFound(str(exc)) from exc
    return ProposalInfo(
        id=made.id,
        baseline=made.baseline,
        actor=made.actor,
        reason=reason_text(root, made.reason_ref),
        paths=made.paths,
        status=made.status,
        created=made.created,
        decided_by=made.decided_by,
    )


def _direct(rules: Rules, path: str, change: FileDiff) -> Decision | None:
    classes = _classes(path, change)
    for entry in rules.direct:
        glob, _, name = entry.rpartition(":")
        allowed = _GROUPS.get(name)
        if glob and allowed is not None and _matches(glob, path) and classes and classes <= allowed:
            return Decision("direct", entry)
    return None


def _classes(path: str, change: FileDiff) -> frozenset[str]:
    raw = change.details.get("classes")
    if isinstance(raw, (list, tuple, set, frozenset)):
        return frozenset(str(item) for item in raw)
    before = "\n".join(block.before for block in change.blocks).encode()
    after = "\n".join(block.after for block in change.blocks).encode()
    return classify(path, before, after)


def _forced(rules: Rules, path: str) -> bool:
    if Path(path).suffix.lower() in _FORCED:
        return True
    return any(_matches(glob, path) for glob in rules.propose_always)


def _matches(pattern: str, path: str) -> bool:
    if pattern == "**":
        return True
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return path == prefix or path.startswith(prefix + "/")
    if pattern.startswith("**/"):
        tail = pattern[3:]
        if "/" not in tail:
            return fnmatch.fnmatchcase(Path(path).name, tail)
        return fnmatch.fnmatchcase(path, tail)
    return fnmatch.fnmatchcase(path, pattern)


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _bytes(root: Path, path: str) -> bytes:
    full = root / path
    if not full.is_file():
        return b""
    return full.read_bytes()


def _deletion(root: Path, path: str, text: str) -> bool:
    if text != "":
        return False
    full = root / path
    return full.is_file() and full.stat().st_size > 0
