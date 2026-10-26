"""Accepting a proposal, and deciding or editing one change of it, on the real bridge."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Protocol, cast

from iterthink.compare.engines import diff as diff_bytes
from iterthink.persistence.snapshots import SnapshotError, Snapshots
from iterthink.services.bridge import (
    Conflict,
    FileDiff,
    Invalid,
    NotFound,
    ProposalInfo,
    VersionInfo,
    kind_of,
)
from iterthink.services.change_ids import (
    DECIDABLE_KINDS,
    candidate_of,
    change_ids,
    decided_text,
    edited_text,
    recorded,
    statuses,
)
from iterthink.services.event_log import store_blob
from iterthink.services.projects import inside, shown, tracked_files, write_bytes
from iterthink.services.proposals import (
    Proposal,
    compete,
    conflicts,
    load_all,
    reason_text,
    require,
)
from iterthink.services.tasks import on_verdict

Verdict = Literal["accepted", "rejected"]


class _Host(Protocol):
    def _root(self, project: str) -> Path: ...

    def _event(
        self, root: Path, project: str, actor: str, kind: str, payload: dict[str, object]
    ) -> None: ...

    def reject(self, project: str, proposal_id: str, actor: str, reason: str) -> None: ...


def _text_diffs(root: Path, item: Proposal, drafted: Mapping[str, bytes]) -> list[FileDiff]:
    snaps = Snapshots(root)
    found: list[FileDiff] = []
    for rel in item.paths:
        if kind_of(rel) not in DECIDABLE_KINDS:
            continue
        try:
            before = snaps.file_at(item.baseline, rel)
        except SnapshotError:
            before = None
        found.append(diff_bytes(rel, before, drafted.get(rel)))
    return found


def _drafted(root: Path, item: Proposal) -> dict[str, bytes]:
    try:
        return Snapshots(root).read_draft(item.draft)
    except SnapshotError as exc:
        raise NotFound(f"unknown proposal {item.id}") from exc


def proposal_info(root: Path, item: Proposal) -> ProposalInfo:
    """The contract record. Change states and the candidate only while it is open."""
    changes = recorded(item.verdicts)
    candidate = ""
    if item.status == "open":
        drafted = _drafted(root, item)
        changes = statuses(_text_diffs(root, item, drafted), item.verdicts, "open")
        candidate = candidate_of(drafted)
    return ProposalInfo(
        id=item.id,
        baseline=item.baseline,
        actor=item.actor,
        reason=reason_text(root, item.reason_ref),
        paths=item.paths,
        status=item.status,
        created=item.created,
        decided_by=item.decided_by,
        changes=changes,
        candidate=candidate,
    )


def _app_bytes(drafted: Mapping[str, bytes]) -> dict[str, bytes]:
    """An accepted app stays in the version. Other iterthink data does not."""
    kept: dict[str, bytes] = {}
    for rel, data in drafted.items():
        parts = rel.split("/")
        own = len(parts) == 4 and parts[:2] == [".iterthink", "apps"]
        if own and not parts[2].startswith("."):
            kept[rel] = data
    return kept


def accept_files(
    host: _Host,
    project: str,
    found: Proposal,
    files: Mapping[str, bytes] | None,
    actor: str,
    reason: str,
    partial: bool = False,
) -> VersionInfo:
    """Write the proposed bytes (the draft when ``files`` is None) and log the verdict."""
    root = host._root(project)
    stale = conflicts(found, Snapshots(root), root)
    if stale:
        host._event(root, project, actor, "conflict", {"paths": stale, "proposal": found.id})
        raise Conflict(f"{', '.join(stale)} changed since the proposal was made")
    drafted = dict(files) if files is not None else _drafted(root, found)
    for rel, data in drafted.items():
        write_bytes(inside(root, rel), data)
    note = reason.strip() or reason_text(root, found.reason_ref)
    snaps = Snapshots(root)
    tracked = tracked_files(root)
    tracked.update(_app_bytes(drafted))
    version = snaps.snapshot(tracked, f"accepted {note}".strip(), actor)
    made = shown(version if version is not None else snaps.head())
    payload: dict[str, object] = {
        "proposal": found.id,
        "reason": store_blob(root, note),
        "verdict": "accepted",
        "version": made.id,
    }
    if actor.startswith("rule:"):
        payload["auto"] = True
    if partial:
        payload["partial"] = True
    host._event(root, project, actor, "verdict", payload)
    compete(root, Snapshots(root), project, found.id, found.paths, actor, host._event)
    on_verdict(host, project, found.id, "accepted", actor, reason)
    return made


def _open_state(
    root: Path, proposal_id: str, candidate: str | None
) -> tuple[Proposal, dict[str, bytes], list[FileDiff]]:
    found = require(root, Snapshots(root), proposal_id)
    if found.status != "open":
        raise Conflict(f"proposal {proposal_id} is already {found.status}")
    drafted = _drafted(root, found)
    if candidate is not None and candidate != candidate_of(drafted):
        raise Conflict(f"proposal {proposal_id} changed since it was shown")
    return found, drafted, _text_diffs(root, found, drafted)


def _info_by_id(root: Path, proposal_id: str) -> ProposalInfo:
    found = next(item for item in load_all(root, Snapshots(root)) if item.id == proposal_id)
    return proposal_info(root, found)


def _decided_files(
    drafted: Mapping[str, bytes], diffs: list[FileDiff], verdicts: Mapping[str, str]
) -> dict[str, bytes]:
    files = dict(drafted)
    for diff in diffs:
        proposed = drafted.get(diff.path, b"").decode("utf-8")
        files[diff.path] = decided_text(diff.blocks, verdicts, proposed).encode("utf-8")
    return files


class ChangeVerdictsBridge:
    """`decide_change` and `edit_change`. Source files stay put until the last change."""

    def decide_change(
        self,
        project: str,
        proposal_id: str,
        change_id: str,
        verdict: Verdict,
        actor: str,
        reason: str = "",
        candidate: str | None = None,
    ) -> ProposalInfo:
        host = cast(_Host, self)
        root = host._root(project)
        found, drafted, diffs = _open_state(root, proposal_id, candidate)
        if change_id not in change_ids(diffs):
            raise NotFound(f"unknown change {change_id}")
        if verdict not in ("accepted", "rejected"):
            raise Invalid(f"unknown verdict {verdict!r}")
        verdicts = {**found.verdicts, change_id: verdict}
        current = set(statuses(diffs, verdicts, "open").values())
        last = "open" not in current
        if last and "accepted" not in current and not reason.strip():
            raise Invalid("rejecting every change needs a reason")
        payload: dict[str, object] = {"change": change_id, "proposal": proposal_id}
        payload["verdict"] = verdict
        if reason.strip():
            payload["reason"] = store_blob(root, reason)
        host._event(root, project, actor, "change_verdict", payload)
        if last and "accepted" in current:
            files = _decided_files(drafted, diffs, verdicts)
            accept_files(host, project, found, files, actor, reason, "rejected" in current)
        elif last:
            host.reject(project, proposal_id, actor, reason)
        return _info_by_id(root, proposal_id)

    def edit_change(
        self,
        project: str,
        proposal_id: str,
        change_id: str,
        text: str,
        actor: str,
        candidate: str | None = None,
    ) -> ProposalInfo:
        host = cast(_Host, self)
        root = host._root(project)
        found, drafted, diffs = _open_state(root, proposal_id, candidate)
        target = next((d for d in diffs if change_id in change_ids([d])), None)
        if target is None:
            raise NotFound(f"unknown change {change_id}")
        if not text.strip():
            raise Invalid("an edited change needs text")
        proposed = drafted.get(target.path, b"").decode("utf-8")
        rebuilt = edited_text(target.blocks, change_id, text.strip(), proposed)
        files = {**drafted, target.path: rebuilt.encode("utf-8")}
        made = Snapshots(root).draft(found.baseline, files, f"edited {proposal_id}", actor)
        payload: dict[str, object] = {"change": change_id, "draft": made.id}
        payload["proposal"] = proposal_id
        host._event(root, project, actor, "change_edit", payload)
        return _info_by_id(root, proposal_id)
