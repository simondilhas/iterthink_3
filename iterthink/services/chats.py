"""Project chats: one Markdown file, a claim while it is written, no source edits."""

from __future__ import annotations

import re
import secrets
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from queue import Queue
from typing import Protocol, cast

import yaml

from iterthink.persistence.snapshots import Snapshots
from iterthink.services.bridge import (
    Bridge,
    ChatInfo,
    ChatMessage,
    Forbidden,
    Invalid,
    NotFound,
    ProposalInfo,
    SearchHit,
)
from iterthink.services.claims import Claimed, acquire, heartbeat, holder, take_over
from iterthink.services.documents import create
from iterthink.services.egress import ShieldedText, Tier, check, prepare, restore
from iterthink.services.indexer import Index, index_for
from iterthink.services.projects import tracked_files, write_bytes
from iterthink.services.search import hybrid

_HEAD = re.compile(r"^## (user|assistant) · (\S+)\s*$", re.M)


class Router(Protocol):
    model: str
    tier: str

    def stream(self, system: str, user: str, tier: str) -> Iterator[str]: ...


class _Real(Protocol):
    state_dir: Path
    machine: str

    def _root(self, project: str) -> Path: ...
    def _event(
        self, root: Path, project: str, actor: str, kind: str, payload: dict[str, object]
    ) -> None: ...
    def propose(
        self,
        project: str,
        changes: dict[str, str],
        actor: str,
        reason: str,
        baseline: str | None = None,
    ) -> ProposalInfo: ...


def _stamp(moment: datetime | None = None) -> str:
    current = moment or datetime.now(UTC)
    return current.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _path(chat_id: str) -> str:
    return f".iterthink/chats/{chat_id}.md"


def _load(root: Path, chat_id: str) -> tuple[str, dict[str, object], str]:
    rel = _path(chat_id)
    file = root / rel
    if not file.is_file():
        raise NotFound(f"unknown chat {chat_id}")
    text = file.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise Invalid("a chat file needs front matter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise Invalid("a chat file needs front matter")
    loaded = yaml.safe_load(text[4:end])
    meta = loaded if isinstance(loaded, dict) else {}
    return rel, {str(key): value for key, value in meta.items()}, text[end + 5 :]


def _messages(body: str) -> list[ChatMessage]:
    found: list[ChatMessage] = []
    matches = list(_HEAD.finditer(body))
    for index, match in enumerate(matches):
        start = match.end()
        stop = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        role = match.group(1)
        kind: ChatMessage = ChatMessage(
            "assistant" if role == "assistant" else "user",
            body[start:stop].strip(),
            match.group(2),
        )
        found.append(kind)
    return found


def _refs(meta: dict[str, object]) -> tuple[str, ...]:
    raw = meta.get("references")
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str))


def _info(chat_id: str, meta: dict[str, object]) -> ChatInfo:
    title = meta.get("title")
    return ChatInfo(
        id=chat_id,
        title=title if isinstance(title, str) else chat_id,
        path=_path(chat_id),
        references=_refs(meta),
    )


def _render(meta: dict[str, object], body: str) -> str:
    dumped = yaml.safe_dump(meta, allow_unicode=True, sort_keys=True).strip()
    text = body if body.startswith("\n") else f"\n{body}"
    return f"---\n{dumped}\n---\n{text}"


def _section(role: str, text: str) -> str:
    return f"\n## {role} · {_stamp()}\n\n{text.strip()}\n"


def _title(text: str) -> str:
    line = text.strip().splitlines()[0] if text.strip() else "Chat"
    return line[:80]


def _index(state_dir: Path, project: str) -> Index:
    """Open the project index. A second try covers a concurrent first create."""
    from sqlalchemy.exc import OperationalError

    try:
        return index_for(state_dir, project)
    except OperationalError:
        return index_for(state_dir, project)


def _hits(state_dir: Path, project: str, root: Path, query: str) -> list[SearchHit]:
    index = _index(state_dir, project)
    index.update(root)
    return [hit for hit in hybrid(index, project, query, 8) if not hit.path.startswith(".")]


def _context(hits: list[SearchHit]) -> str:
    return "\n".join(f"{hit.path}:{hit.line}: {hit.snippet}" for hit in hits)


def _cited(answer: str, paths: tuple[str, ...]) -> str:
    links = "\n".join(f"[{path}]({path})" for path in paths)
    return f"{answer.strip()}\n\n{links}".strip() if links else answer.strip()


def _ours(machine: str, actor: str, root: Path, rel: str) -> None:
    current = holder(root, rel)
    if current is not None and (current.machine != machine or current.user != actor):
        raise Forbidden(f"{current.user} is writing this chat")
    if current is not None:
        heartbeat(root, current)
        return
    try:
        acquire(root, rel, machine=machine, user=actor)
    except Claimed as exc:
        _resume(root, rel, machine, actor, exc)


def _resume(root: Path, rel: str, machine: str, actor: str, exc: Claimed) -> None:
    """A quiet claim can be taken. A live one stays with its writer."""
    try:
        take_over(root, rel, machine=machine, user=actor, actor=actor)
    except Claimed:
        raise Forbidden(f"{exc.holder.user} is writing this chat") from None


def _store(
    host: _Real, project: str, root: Path, rel: str, text: str, actor: str, note: str
) -> None:
    write_bytes(root / rel, text.encode("utf-8"))
    files = tracked_files(root)
    files[rel] = (root / rel).read_bytes()
    made = Snapshots(root).snapshot(files, note, actor)
    if made is None:
        return
    host._event(root, project, actor, "version", {"kind": "chat", "path": rel, "version": made.id})


def _level(root: Path, asked: str) -> Tier:
    tier: Tier = cast(Tier, asked) if asked in {"local", "company", "cloud"} else "local"
    if check(root, "chat", tier) == "deny":
        return "local"
    return tier


def _pump(router: Router, system: str, user: str, tier: str, box: Queue[str | None]) -> None:
    try:
        for chunk in router.stream(system, user, tier):
            box.put(chunk)
    finally:
        box.put(None)


def _relay(box: Queue[str | None], mapping: dict[str, str]) -> Iterator[str]:
    raw = ""
    shown = ""
    while True:
        item = box.get(timeout=30)
        if item is None:
            return
        raw += item
        full = restore(ShieldedText("", mapping, "send"), raw)
        delta = full[len(shown) :]
        shown = full
        if delta:
            yield delta


class ChatsBridge:
    """Chat methods on the real bridge. The model is set with `use_model`."""

    def use_model(self, router: Router) -> None:
        self._chat_model = router

    def _model(self) -> Router:
        found = getattr(self, "_chat_model", None)
        if not hasattr(found, "stream"):
            raise Invalid("no model is configured")
        return cast(Router, found)

    def chat_start(self, project: str, text: str, actor: str) -> ChatInfo:
        host = cast(_Real, self)
        root = host._root(project)
        if not text.strip():
            raise Invalid("a chat needs a question")
        chat_id = f"c-{secrets.token_hex(4)}"
        rel = _path(chat_id)
        hits = _hits(host.state_dir, project, root, text)
        refs = tuple(dict.fromkeys(hit.path for hit in hits))
        meta: dict[str, object] = {
            "created": _stamp(),
            "id": chat_id,
            "references": list(refs),
            "title": _title(text),
        }
        opened = _render(meta, _section("user", text))
        _store(host, project, root, rel, opened, actor, "started a chat")
        acquire(root, rel, machine=host.machine, user=actor)
        return _info(chat_id, meta)

    def chat_send(self, project: str, chat_id: str, text: str, actor: str) -> Iterator[str]:
        host = cast(_Real, self)
        root = host._root(project)
        rel = _path(chat_id)
        _ours(host.machine, actor, root, rel)
        if not text.strip():
            raise Invalid("a chat needs a question")
        _, meta, body = _load(root, chat_id)
        hits = _hits(host.state_dir, project, root, text)
        refs = tuple(dict.fromkeys((*_refs(meta), *(hit.path for hit in hits))))
        meta["references"] = list(refs)
        asked = _render(meta, body + _section("user", text))
        _store(host, project, root, rel, asked, actor, "asked in a chat")
        yield from _answer(host, project, root, rel, meta, text, actor, hits)

    def chat_messages(self, project: str, chat_id: str) -> list[ChatMessage]:
        _, _, body = _load(cast(_Real, self)._root(project), chat_id)
        return _messages(body)

    def chats(self, project: str) -> list[ChatInfo]:
        root = cast(_Real, self)._root(project)
        folder = root / ".iterthink" / "chats"
        if not folder.is_dir():
            return []
        names = sorted(path.stem for path in folder.glob("c-*.md"))
        found = [_info(name, _load(root, name)[1]) for name in names]
        return sorted(found, key=lambda item: item.title)

    def chat_locked(self, project: str, chat_id: str, actor: str) -> str:
        host = cast(_Real, self)
        current = holder(host._root(project), _path(chat_id))
        if current is None or (current.machine == host.machine and current.user == actor):
            return ""
        return current.user

    def chat_proposal(
        self, project: str, chat_id: str, index: int, path: str, actor: str
    ) -> ProposalInfo:
        host = cast(_Real, self)
        messages = self.chat_messages(project, chat_id)
        if index < 0 or index >= len(messages):
            raise Invalid("that message is not in the chat")
        reason = "from a chat"
        return host.propose(project, {path: messages[index].text + "\n"}, actor, reason)

    def chat_document(self, project: str, chat_id: str, folder: str, name: str, actor: str) -> str:
        host = cast(_Real, self)
        root = host._root(project)
        _, meta, body = _load(root, chat_id)
        title = meta.get("title")
        heading = title if isinstance(title, str) else name
        rel = create(cast(Bridge, self), project, folder, name, heading, actor)
        transcript = "\n\n".join(message.text for message in _messages(body))
        cast(Bridge, self).save(project, rel, f"# {heading}\n\n{transcript}\n", actor, heading)
        note = f"\nSaved as [{rel}]({rel}).\n"
        saved = _render(meta, body + note)
        _store(host, project, root, _path(chat_id), saved, actor, "saved a chat as a document")
        return rel


def _remember(
    host: _Real,
    project: str,
    root: Path,
    rel: str,
    meta: dict[str, object],
    chat_id: str,
    parts: list[str],
    hits: list[SearchHit],
    actor: str,
) -> None:
    answer = _cited("".join(parts), tuple(hit.path for hit in hits))
    _, fresh, body = _load(root, chat_id)
    fresh["references"] = meta.get("references")
    stored = _render(fresh, body + _section("assistant", answer))
    _store(host, project, root, rel, stored, actor, "answered in a chat")


def _answer(
    host: _Real,
    project: str,
    root: Path,
    rel: str,
    meta: dict[str, object],
    text: str,
    actor: str,
    hits: list[SearchHit],
) -> Iterator[str]:
    router = cast(ChatsBridge, host)._model()
    asked = getattr(router, "tier", "local")
    tier = _level(root, asked if isinstance(asked, str) else "local")
    prompt = f"{_context(hits)}\n\n{text}".strip()
    prepared = prepare(root, prompt, "chat", tier)
    system = "Answer from the project notes. Cite file paths you used."
    box: Queue[str | None] = Queue()
    threading.Thread(
        target=_pump,
        args=(router, system, prepared.text, tier, box),
        name="iterthink-chat",
        daemon=True,
    ).start()
    parts: list[str] = []
    chat_id = Path(rel).stem
    try:
        for delta in _relay(box, prepared.placeholders):
            parts.append(delta)
            yield delta
    finally:
        _remember(host, project, root, rel, meta, chat_id, parts, hits, actor)
