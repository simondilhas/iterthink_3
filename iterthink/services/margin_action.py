"""Margin actions: prompts, the model call, the log line, and the proposal."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Generator, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import Protocol, cast

import yaml

from iterthink.compare.margin import join_paragraphs, paragraph_index_at_offset, split_paragraphs
from iterthink.services.bridge import (
    FileContent,
    FileDiff,
    Invalid,
    NotFound,
    ProposalInfo,
    ProposalStatus,
    VersionInfo,
)
from iterthink.services.egress import ShieldedText, Tier, check, prepare, restore
from iterthink.services.event_log import append, store_blob
from iterthink.services.projects import inside, relative, settings_of
from iterthink.services.proposals import CONTRACT

_SEED = Path(__file__).resolve().parents[1] / "defaults" / "prompts.yaml"


@dataclass(frozen=True)
class MarginAction:
    id: str
    label: str
    topic: str
    system_prompt: str
    user_template: str


class Router(Protocol):
    """A streaming model. Tests pass a fake; the call stays off the request thread."""

    model: str
    tier: str

    def stream(self, system: str, user: str, tier: str) -> Iterator[str]: ...


class Host(Protocol):
    def _root(self, project: str) -> Path: ...
    def read(self, project: str, path: str) -> FileContent: ...
    def save(
        self, project: str, path: str, text: str, actor: str, message: str = ""
    ) -> VersionInfo | None: ...
    def propose(
        self,
        project: str,
        changes: Mapping[str, str],
        actor: str,
        reason: str,
        baseline: str | None = None,
    ) -> ProposalInfo: ...
    def proposals(
        self, project: str, status: ProposalStatus | None = "open"
    ) -> list[ProposalInfo]: ...
    def proposal_diff(self, project: str, proposal_id: str) -> list[FileDiff]: ...


_FREE = MarginAction(
    id="instruction",
    label="Instruction",
    topic="change",
    system_prompt=(
        "Revise the text as the instruction asks. Reply with only the replacement. "
        "Keep the input language."
    ),
    user_template="{text}",
)


def margin_actions(project_dir: Path) -> list[MarginAction]:
    """Margin actions from the project copy of prompts.yaml, else the bundled seed."""
    return list(_load(project_dir))


def run_margin_action(
    project_dir: Path,
    *,
    path: str,
    paragraph: int,
    selection: str | None,
    action_id: str,
    instruction: str | None,
    router: Router,
    draft: str | None = None,
    bridge: Host | None = None,
    actor: str = "user:local",
    project: str = "",
    offset: int = -1,
) -> Iterator[str]:
    """Stream one margin action. An edit becomes a proposal; the file stays as it is."""
    if bridge is not None:
        _save(bridge, project, path, draft, actor)
    source = _read(project_dir, path)
    index = _index(source, paragraph, offset)
    action = _action(project_dir, action_id, instruction)
    body = _body(source, index, selection)
    user = _user(action, body, instruction)
    tier = _level(project_dir, _asked(router))
    prepared = prepare(project_dir, user, "chat", tier)
    box = _start(router, action.system_prompt, prepared.text, tier)
    answer = yield from _relay(box, prepared.placeholders)
    _record(project_dir, project, actor, path, index, action, _model(router), body, answer)
    if action.topic == "change":
        _propose(
            bridge, project, path, source, index, selection, answer, actor, action, instruction
        )


def _prompts_file(project_dir: Path) -> Path:
    local = project_dir / ".iterthink" / "prompts.yaml"
    if local.is_file():
        return local
    return _SEED


def _load(project_dir: Path) -> tuple[MarginAction, ...]:
    loaded = yaml.safe_load(_prompts_file(project_dir).read_text(encoding="utf-8"))
    rows = loaded.get("margin_actions") if isinstance(loaded, dict) else None
    if not isinstance(rows, list) or not rows:
        raise Invalid("margin actions are missing")
    return tuple(_row(row) for row in rows)


def _row(row: object) -> MarginAction:
    if not isinstance(row, dict):
        raise Invalid("a margin action must be a mapping")
    data = {str(key): value for key, value in row.items()}
    aid = _field(data, "id")
    topic = data.get("topic")
    name = topic.strip() if isinstance(topic, str) and topic.strip() else "change"
    if name not in {"discuss", "change", "evaluate"}:
        raise Invalid(f"{aid} has an unknown topic")
    template = data.get("user_template")
    if not isinstance(template, str) or "{text}" not in template:
        raise Invalid(f"{aid} needs {{text}} in its template")
    return MarginAction(aid, _field(data, "label"), name, _field(data, "system_prompt"), template)


def _field(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise Invalid(f"margin action needs {key}")
    return value.strip()


def _save(bridge: Host, project: str, path: str, draft: str | None, actor: str) -> None:
    if not draft or not project:
        return
    current = bridge.read(project, path)
    if current.text != draft:
        bridge.save(project, path, draft, actor)


def _read(project_dir: Path, path: str) -> str:
    rel = relative(path)
    file = inside(project_dir, rel)
    if not file.is_file():
        raise NotFound(rel)
    return file.read_text(encoding="utf-8")


def _index(text: str, paragraph: int, offset: int) -> int:
    if paragraph >= 0:
        return paragraph
    if offset >= 0:
        return paragraph_index_at_offset(text, offset)
    raise Invalid("choose a paragraph")


def _action(project_dir: Path, action_id: str, instruction: str | None) -> MarginAction:
    key = action_id.strip()
    if not key:
        if not (instruction or "").strip():
            raise Invalid("choose an action or write an instruction")
        return _FREE
    for action in _load(project_dir):
        if action.id == key:
            return action
    raise Invalid(f"unknown margin action {key}")


def _body(text: str, paragraph: int, selection: str | None) -> str:
    parts = split_paragraphs(text)
    if paragraph < 0 or paragraph >= len(parts):
        raise Invalid("that paragraph is not in the document")
    if selection:
        return selection
    return parts[paragraph]


def _user(action: MarginAction, body: str, instruction: str | None) -> str:
    prompt = action.user_template.replace("{text}", body)
    extra = (instruction or "").strip()
    if extra:
        return f"{prompt}\n\n{extra}"
    return prompt


def _asked(router: Router) -> str:
    tier = getattr(router, "tier", "local")
    return tier if isinstance(tier, str) else "local"


def _model(router: Router) -> str:
    model = getattr(router, "model", "")
    return model if isinstance(model, str) else ""


def _level(project_dir: Path, asked: str) -> Tier:
    tier: Tier = cast(Tier, asked) if asked in {"local", "company", "cloud"} else "local"
    if check(project_dir, "chat", tier) == "deny":
        return "local"
    return tier


def _start(router: Router, system: str, user: str, tier: str) -> Queue[str | None]:
    box: Queue[str | None] = Queue()
    threading.Thread(
        target=_pump,
        args=(router, system, user, tier, box),
        name="iterthink-margin",
        daemon=True,
    ).start()
    return box


def _pump(router: Router, system: str, user: str, tier: str, box: Queue[str | None]) -> None:
    try:
        for chunk in router.stream(system, user, tier):
            box.put(chunk)
    finally:
        box.put(None)


def _relay(box: Queue[str | None], mapping: dict[str, str]) -> Generator[str, None, str]:
    raw = ""
    shown = ""
    while True:
        item = box.get(timeout=30)
        if item is None:
            break
        raw += item
        full = restore(ShieldedText("", mapping, "send"), raw)
        delta = full[len(shown) :]
        shown = full
        if delta:
            yield delta
    return shown


def _record(
    project_dir: Path,
    project: str,
    actor: str,
    path: str,
    paragraph: int,
    action: MarginAction,
    model: str,
    body: str,
    answer: str,
) -> None:
    payload: dict[str, object] = {
        "action": action.id,
        "answer": store_blob(project_dir, answer),
        "model": model,
        "paragraph": paragraph,
        "path": relative(path),
        "prompt_version": hashlib.sha256(action.system_prompt.encode()).hexdigest(),
        "text": store_blob(project_dir, body),
    }
    append(
        project_dir,
        machine=_machine(project_dir),
        actor=actor,
        type="margin",
        project=project or _project_id(project_dir),
        payload=payload,
        contract=CONTRACT,
    )


def _propose(
    bridge: Host | None,
    project: str,
    path: str,
    source: str,
    paragraph: int,
    selection: str | None,
    answer: str,
    actor: str,
    action: MarginAction,
    instruction: str | None,
) -> None:
    if bridge is None or not project:
        raise Invalid("a proposal needs the project")
    revised = _replace(source, paragraph, selection, answer)
    reason = (instruction or "").strip() or action.label
    bridge.propose(project, {relative(path): revised}, actor, reason)


def _replace(text: str, paragraph: int, selection: str | None, answer: str) -> str:
    parts = split_paragraphs(text)
    if paragraph < 0 or paragraph >= len(parts):
        raise Invalid("that paragraph is not in the document")
    slot = _slot(parts[paragraph], selection, answer)
    return join_paragraphs([*parts[:paragraph], slot, *parts[paragraph + 1 :]])


def _slot(paragraph: str, selection: str | None, answer: str) -> str:
    if selection and selection in paragraph:
        return paragraph.replace(selection, answer, 1)
    return answer


def _machine(project_dir: Path) -> str:
    folder = project_dir / ".iterthink" / "log"
    if not folder.is_dir():
        return "m-local"
    logs = sorted(path for path in folder.glob("*.jsonl") if path.is_file())
    if len(logs) == 1:
        return logs[0].stem
    return "m-local"


def _project_id(project_dir: Path) -> str:
    found = settings_of(project_dir).get("id")
    return found if isinstance(found, str) else ""
