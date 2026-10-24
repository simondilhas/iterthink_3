"""Markdown documents. Margin actions live in `margin_action`."""

from __future__ import annotations

import secrets
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import cast

from iterthink.services.bridge import Bridge, Invalid, NotFound
from iterthink.services.margin_action import (
    Host,
    MarginAction,
    Router,
    margin_actions,
    run_margin_action,
)
from iterthink.services.projects import inside, relative

_TOPICS = (("discuss", "Discuss"), ("change", "Edit"), ("evaluate", "Evaluate"))
_JOBS: dict[str, Iterator[str]] = {}
_GUARD = threading.Lock()


class _Unset:
    """Used when the page has no model. It never opens a socket."""

    model = "local"
    tier = "local"

    def stream(self, system: str, user: str, tier: str) -> Iterator[str]:
        raise Invalid("no model is configured")


def create(bridge: Bridge, project: str, folder: str, name: str, title: str, actor: str) -> str:
    """Write `<name>.md` with a heading. An existing file is left untouched."""
    rel = _new_path(folder, name)
    target = inside(_folder(bridge, project), rel)
    if target.exists():
        raise Invalid(f"{rel} already exists")
    heading = _heading(title)
    bridge.save(project, rel, f"# {heading}\n", actor, heading)
    return rel


def _new_path(folder: str, name: str) -> str:
    stem = name.strip()
    if stem.lower().endswith(".md"):
        stem = stem[:-3].strip()
    if not stem or "/" in stem or "\\" in stem:
        raise Invalid("choose a file name")
    parent = folder.strip().strip("/")
    return relative(f"{parent}/{stem}.md" if parent else f"{stem}.md")


def _heading(title: str) -> str:
    heading = " ".join(title.split())
    if not heading:
        raise Invalid("a document needs a title")
    return heading


def _folder(bridge: Bridge, project: str) -> Path:
    for item in bridge.projects():
        if item.id == project:
            return Path(item.path)
    raise NotFound(f"unknown project {project}")


def _groups(actions: list[MarginAction]) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    for topic, title in _TOPICS:
        chosen = [{"id": item.id, "label": item.label} for item in actions if item.topic == topic]
        if chosen:
            groups.append({"title": title, "actions": chosen})
    return groups


def _open(host: Host, project: str, path: str) -> dict[str, object] | None:
    rel = relative(path)
    for item in host.proposals(project):
        if rel not in item.paths:
            continue
        diffs = host.proposal_diff(project, item.id)
        found = next((diff for diff in diffs if diff.path == rel), None)
        if found is not None:
            return {"id": item.id, "reason": item.reason, "diff": found}
    return None


def _keep(stream: Iterator[str]) -> str:
    token = secrets.token_hex(8)
    with _GUARD:
        _JOBS[token] = stream
    return token


def _pop(token: str) -> Iterator[str]:
    with _GUARD:
        found = _JOBS.pop(token, None)
    if found is None:
        raise NotFound("that answer is no longer streaming")
    return found


class DocumentsBridge:
    """Real-bridge methods the document page reaches without importing this module."""

    def doc_context(self, project: str, path: str) -> dict[str, object]:
        host = cast(Host, self)
        root = host._root(project)
        rel = relative(path)
        content = host.read(project, rel)
        return {
            "change": _open(host, project, rel),
            "groups": _groups(margin_actions(root)),
            "path": rel,
            "text": content.text or "",
        }

    def doc_begin(
        self,
        project: str,
        path: str,
        *,
        paragraph: int,
        offset: int,
        selection: str,
        action_id: str,
        instruction: str,
        draft: str,
        router: Router,
        actor: str,
    ) -> str:
        host = cast(Host, self)
        stream = run_margin_action(
            host._root(project),
            path=path,
            paragraph=paragraph,
            selection=selection or None,
            action_id=action_id,
            instruction=instruction.strip() or None,
            router=router,
            draft=draft,
            bridge=host,
            actor=actor,
            project=project,
            offset=offset,
        )
        return _keep(stream)

    def doc_take(self, token: str) -> Iterator[str]:
        return _pop(token)

    def doc_router(self, project: str) -> Router:
        cast(Host, self)._root(project)
        return _Unset()
