"""Classify a line on Enter. Rules first, then a local model if one is configured."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from secrets import token_hex
from typing import Literal, Protocol, cast
from urllib.parse import quote

from iterthink import config
from iterthink.services.bridge import (
    Bridge,
    ChatInfo,
    FileEntry,
    Intent,
    Invalid,
    Mode,
    ProjectInfo,
    VersionInfo,
)
from iterthink.services.egress import check
from iterthink.services.event_log import store_blob

PROMPT_ID = "intent-v1"
PROMPT = (
    "Classify one line as search, document, chat, app, or task. "
    "Reply with the mode and a confidence between 0 and 1, for example: chat 0.8. "
    "Do not write the document, the answer, or the task."
)

_MODES = {"search", "document", "chat", "app", "task"}
_DOCUMENT = re.compile(r"^(?:new document|neues dokument)(?: (?P<title>.+))?$", re.I)
_REVIEW = re.compile(r"^(?:compare|vergleiche) (?P<a>.+?) (?:and|und) (?P<b>.+)$", re.I)
_SEARCH = re.compile(r"^(?:find|where|which document)\b", re.I)
_APP = re.compile(r"\b(?:schedule|liste)\b", re.I)
_SCORE = re.compile(
    r"^(?P<mode>search|document|chat|app|task)"
    r"(?:\s+(?P<confidence>0(?:\.\d+)?|1(?:\.0+)?))?$"
)


@dataclass(frozen=True)
class LineContext:
    project: str
    open_path: str | None
    recent_paths: tuple[str, ...]


@dataclass(frozen=True)
class Classified:
    intent: Intent
    confidence: float
    alternatives: tuple[Mode, ...]
    via: Literal["rule", "model"]
    review: bool = False
    reopen: str | None = None


class Router(Protocol):
    model: str
    tier: str

    def complete(self, system: str, user: str, tier: str) -> str: ...


class _Host(Protocol):
    state_dir: Path
    machine: str

    def _root(self, project: str) -> Path: ...
    def _event(
        self, root: Path, project: str, actor: str, kind: str, payload: dict[str, object]
    ) -> None: ...
    def files(self, project: str) -> list[FileEntry]: ...
    def history(self, project: str, path: str | None = None) -> list[VersionInfo]: ...
    def make_project(self, path: Path) -> ProjectInfo: ...
    def search(self, project: str, query: str, limit: int = 50) -> list[object]: ...


def _intent(mode: Mode, title: str, *steps: str) -> Intent:
    return Intent(mode=mode, title=title, plan=steps)


def _alts(mode: Mode) -> tuple[Mode, ...]:
    order: tuple[Mode, ...] = ("document", "chat", "search")
    return tuple(item for item in order if item != mode)


def _titled(
    mode: Mode,
    title: str,
    *steps: str,
    review: bool = False,
    reopen: str | None = None,
) -> Classified:
    return Classified(_intent(mode, title, *steps), 1.0, _alts(mode), "rule", review, reopen)


def _file_hit(host: _Host, project: str, line: str) -> str | None:
    names = {entry.path: entry.path for entry in host.files(project)}
    if line in names:
        return line
    stems = [path for path in names if path.endswith("/" + line) or Path(path).name == line]
    if len(stems) == 1:
        return stems[0]
    return None


def _recent(host: _Host, project: str) -> str | None:
    for version in host.history(project):
        if version.paths:
            return version.paths[0]
    return None


def rules(host: _Host | None, project: str, line: str) -> Classified | None:
    """A fixed phrase. None when the line needs the model."""
    text = " ".join(line.split())
    if not text:
        return None
    if text.casefold() == "continue" and host is not None and project:
        path = _recent(host, project)
        if path:
            return _titled("search", text, "reopen", reopen=path)
    if host is not None and project:
        found = _file_hit(host, project, text)
        if found:
            return _titled("search", text, "reopen", reopen=found)
    document = _DOCUMENT.match(text)
    if document:
        title = document.group("title") or "Untitled"
        return _titled("document", title, "write the file")
    if _REVIEW.match(text):
        return _titled("search", text, "review", review=True)
    if text.endswith("?"):
        return _titled("chat", text, "answer")
    if _APP.search(text):
        return _titled("app", text, "build")
    if _SEARCH.match(text):
        return _titled("search", text, "search")
    return None


def _parse_model(text: str) -> tuple[Mode, float] | None:
    match = _SCORE.match(" ".join(text.split()).casefold())
    if not match:
        return None
    mode = cast(Mode, match.group("mode"))
    raw = match.group("confidence")
    return mode, float(raw) if raw else 0.8


def _from_model(router: Router, line: str, tier: str) -> Classified | None:
    parsed = _parse_model(router.complete(PROMPT, line, tier))
    if parsed is None:
        return None
    mode, confidence = parsed
    return Classified(_intent(mode, line, mode), confidence, _alts(mode), "model")


def classify(
    host: _Host | None,
    project: str,
    line: str,
    router: Router | None,
    *,
    allow_model: bool,
) -> Classified:
    found = rules(host, project, line)
    if found is not None:
        return found
    if router is not None and allow_model:
        parsed = _from_model(router, line, "local" if router.tier == "local" else router.tier)
        if parsed is not None:
            return parsed
    return _titled("search", line, "search")


def _log(
    host: _Host,
    project: str,
    actor: str,
    line: str,
    found: Classified,
    correction: str = "",
) -> None:
    root = host._root(project)
    payload: dict[str, object] = {
        "model": "rule" if found.via == "rule" else "model",
        "prompt": PROMPT_ID,
        "mode": "review" if found.review else found.intent.mode,
        "confidence": f"{found.confidence:.2f}",
        "line": store_blob(root, line),
        "source": _input_source(root),
    }
    if correction:
        payload["correction"] = correction
    host._event(root, project, actor, "intent", payload)


def _input_source(root: Path) -> str:
    from iterthink.services.dictation import take_source

    return take_source(root)


def _slug(title: str) -> str:
    cleaned = " ".join(title.replace("/", " ").replace("\\", " ").split())
    return cleaned or "Untitled"


def _document(host: _Host, project: str, title: str, actor: str) -> str:
    name = _slug(title)
    rel = f"{name}.md"
    try:
        cast(Bridge, host).save(project, rel, f"# {name}\n", actor, name)
    except Invalid:
        return rel
    return rel


def _chat(host: _Host, project: str, line: str) -> ChatInfo:
    """A chat file so the switch has somewhere to go until chats are built."""
    root = host._root(project)
    chat_id = f"c-{token_hex(4)}"
    rel = f".iterthink/chats/{chat_id}.md"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {line}\n", encoding="utf-8")
    return ChatInfo(id=chat_id, title=line, path=rel, references=())


def _query(found: Classified, line: str) -> str:
    label = "review" if found.review else found.intent.mode
    parts = [
        f"opened={quote(label)}",
        f"q={quote(line)}",
        f"sure={'0' if found.confidence < 0.6 else '1'}",
    ]
    parts.extend(f"alt={quote(item)}" for item in found.alternatives)
    return "&".join(parts)


def surface_href(
    project: str, found: Classified, line: str, *, path: str = "", chat: str = ""
) -> str:
    """URL of the opened surface, including the quiet line."""
    extra = _query(found, line)
    if found.reopen:
        return f"/p/{project}/f/{quote(found.reopen)}?{extra}"
    if found.review:
        target = _REVIEW.match(line)
        name = target.group("a") if target else ""
        return f"/p/{project}/diff?path={quote(name)}&{extra}"
    if found.intent.mode == "document" and path:
        return f"/p/{project}/f/{quote(path)}?{extra}"
    if found.intent.mode == "chat" and chat:
        return f"/p/{project}/chats/{quote(chat)}?{extra}"
    if found.intent.mode in {"app", "task"}:
        return f"/p/{project}?soon=1&{extra}"
    return f"/p/{project}/search?q={quote(line)}&{extra}"


def _workspace() -> Path:
    root = config.DOCUMENTS.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _project_dir(title: str) -> Path:
    folder = _workspace() / _slug(title)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


class IntentBridge:
    """Enter classifies the line. The model is whatever the page injected."""

    def use_intent_model(self, router: Router) -> None:
        self._intent_router = router

    def default_workspace(self) -> Path:
        return _workspace()

    def _router(self) -> Router | None:
        found = getattr(self, "_intent_router", None)
        if found is None or not hasattr(found, "complete"):
            return None
        return cast(Router, found)

    def _allowed(self, host: _Host, project: str) -> bool:
        router = self._router()
        if router is None:
            return False
        tier = router.tier if router.tier in {"local", "company", "cloud"} else "local"
        named = cast(Literal["local", "company", "cloud"], tier)
        return check(host._root(project), "chat", named) != "deny"

    def classify_line(
        self, project: str, line: str, switch: str | None = None, actor: str = "user:local"
    ) -> Classified:
        host = cast(_Host, self)
        if switch in _MODES:
            mode = cast(Mode, switch)
            found = Classified(_intent(mode, line, "switch"), 1.0, _alts(mode), "rule")
            _log(host, project, actor, line, found, correction=switch)
            return found
        allowed = self._allowed(host, project)
        found = classify(host, project, line, self._router(), allow_model=allowed)
        _log(host, project, actor, line, found)
        return found

    def interpret(self, project: str, line: str) -> Intent:
        return self.classify_line(project, line).intent

    def open_line(self, project: str, found: Classified, line: str, actor: str) -> str:
        """Create the empty surface and return its path."""
        host = cast(_Host, self)
        if found.reopen or found.review or found.intent.mode == "search":
            return surface_href(project, found, line)
        if found.intent.mode == "document":
            path = _document(host, project, found.intent.title, actor)
            return surface_href(project, found, line, path=path)
        if found.intent.mode == "chat":
            info = _chat(host, project, line)
            return surface_href(project, found, line, chat=info.id)
        return surface_href(project, found, line)

    def start_work(self, line: str, actor: str = "user:local") -> str | None:
        """A start-screen line that is work becomes a project in the default workspace."""
        found = rules(None, "", line)
        if found is None or (found.intent.mode == "search" and not found.review):
            return None
        host = cast(_Host, self)
        info = host.make_project(_project_dir(found.intent.title))
        _log(host, info.id, actor, line, found)
        href = self.open_line(info.id, found, line, actor)
        join = "&" if "?" in href else "?"
        return f"{href}{join}where={quote(str(self.default_workspace()))}"
