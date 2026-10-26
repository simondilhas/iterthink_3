"""Task files under `.iterthink/tasks/`. One Markdown file, one snapshot per change."""

from __future__ import annotations

import fnmatch
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import yaml

from iterthink.persistence.snapshots import Snapshots
from iterthink.services.bridge import Invalid, NotFound, TaskInfo, TaskStatus
from iterthink.services.projects import tracked_files, write_bytes
from iterthink.services.settings import load_yaml

_SPEC = (
    "backlog",
    "ready",
    "running",
    "needs-input",
    "review",
    "done",
    "rejected",
    "cancelled",
)
_RUNNERS = {"local", "cursor", "claude"}
_TIERS = {"local", "company", "cloud"}


class Host(Protocol):
    machine: str

    def _root(self, project: str) -> Path: ...
    def _event(
        self, root: Path, project: str, actor: str, kind: str, payload: dict[str, object]
    ) -> None: ...


@dataclass
class Task:
    """One task file. `status` uses the spec's eight words."""

    id: str
    title: str
    status: str
    agent: str
    runner: str
    inputs: tuple[str, ...]
    scope: tuple[str, ...]
    depends_on: tuple[str, ...]
    budget_tokens: int
    budget_minutes: int
    used_tokens: int
    used_minutes: int
    created_by: str
    body: str
    proposals: tuple[str, ...] = ()
    progress: str = ""
    question: str = ""
    blocked: str = ""
    cursor_agent_id: str = ""
    cursor_run_id: str = ""
    cursor_url: str = ""


@dataclass(frozen=True)
class Profile:
    """One agent profile from agents.yaml."""

    id: str
    runner: str
    model_tier: str
    blocks: tuple[str, ...]
    rules: str
    max_parallel: int
    cursor_model: str


def new_id() -> str:
    return f"t-{secrets.token_hex(4)}"


def path_of(task_id: str) -> str:
    return f".iterthink/tasks/{task_id}.md"


def info(task: Task) -> TaskInfo:
    """Contract view. The file and the contract use the same eight status words."""
    status = cast(TaskStatus, task.status if task.status in _SPEC else "backlog")
    return TaskInfo(
        id=task.id,
        title=task.title,
        path=path_of(task.id),
        status=status,
        depends_on=task.depends_on,
        runner=task.runner or None,
        proposals=task.proposals,
    )


def profiles(root: Path) -> dict[str, Profile]:
    """Inherited agent profiles. Seed, then workspace, then project."""
    found: dict[str, Profile] = {}
    for key, value in load_yaml(root, "agents.yaml").items():
        parsed = _profile(key, value)
        if parsed is not None:
            found[key] = parsed
    return found


def profile(root: Path, name: str) -> Profile:
    found = profiles(root).get(name)
    if found is None:
        raise NotFound(f"unknown agent {name}")
    return found


def load(root: Path, task_id: str) -> Task:
    file = root / path_of(task_id)
    if not file.is_file():
        raise NotFound(f"unknown task {task_id}")
    return parse(file.read_text(encoding="utf-8"))


def load_all(root: Path) -> list[Task]:
    folder = root / ".iterthink" / "tasks"
    if not folder.is_dir():
        return []
    return [parse(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("t-*.md"))]


def parse(text: str) -> Task:
    """Front matter plus the task body."""
    if not text.startswith("---\n"):
        raise Invalid("a task file needs front matter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise Invalid("a task file needs front matter")
    loaded = yaml.safe_load(text[4:end])
    meta = loaded if isinstance(loaded, dict) else {}
    return _from_meta(meta, text[end + 5 :])


def render(task: Task) -> str:
    """Spec front matter, then the body."""
    dumped = yaml.safe_dump(_meta(task), allow_unicode=True, sort_keys=False).strip()
    body = task.body if task.body.endswith("\n") else f"{task.body}\n"
    if not body.startswith("\n"):
        body = f"\n{body}"
    return f"---\n{dumped}\n---\n{body}"


def save(
    host: Host,
    project: str,
    root: Path,
    task: Task,
    actor: str,
    event: str,
    note: str,
    extra: dict[str, object] | None = None,
) -> None:
    """Rewrite the file, snapshot it, and record the event. Never stores a key."""
    if task.status not in _SPEC:
        raise Invalid(f"unknown task status {task.status}")
    write_bytes(root / path_of(task.id), render(task).encode("utf-8"))
    files = tracked_files(root)
    files.update(_task_bytes(root))
    Snapshots(root).snapshot(files, note, actor)
    payload: dict[str, object] = {"status": task.status, "task": task.id}
    if extra:
        payload.update(extra)
    host._event(root, project, actor, event, payload)
    if event != "task_status":
        host._event(root, project, actor, "task_status", {"status": task.status, "task": task.id})


def matches(pattern: str, path: str) -> bool:
    """One scope glob. `**` crosses directories."""
    if pattern in {"**", "**/*"}:
        return True
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return path == prefix or path.startswith(f"{prefix}/")
    if pattern.startswith("**/"):
        tail = pattern[3:]
        if "/" not in tail:
            return fnmatch.fnmatchcase(Path(path).name, tail)
        return fnmatch.fnmatchcase(path, tail)
    return fnmatch.fnmatchcase(path, pattern)


def in_scope(scope: tuple[str, ...], path: str) -> bool:
    return any(matches(pattern, path) for pattern in scope)


def overlaps(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    """True when two scopes can touch the same path."""
    return any(_overlap_one(a, b) for a in left for b in right)


def _overlap_one(left: str, right: str) -> bool:
    a, b = _stem(left), _stem(right)
    if a == "" or b == "":
        return True
    return a == b or a.startswith(f"{b}/") or b.startswith(f"{a}/")


def _stem(pattern: str) -> str:
    if pattern in {"**", "**/*"}:
        return ""
    cleaned = pattern[3:] if pattern.startswith("**/") else pattern
    if cleaned.endswith("/**"):
        cleaned = cleaned[:-3]
    return cleaned.replace("*", "").strip("/")


def _task_bytes(root: Path) -> dict[str, bytes]:
    folder = root / ".iterthink" / "tasks"
    if not folder.is_dir():
        return {}
    found: dict[str, bytes] = {}
    for path in folder.glob("*.md"):
        if not path.name.startswith("."):
            found[f".iterthink/tasks/{path.name}"] = path.read_bytes()
    return found


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _whole(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _profile(key: str, value: object) -> Profile | None:
    data = _mapping(value)
    runner = data.get("runner")
    if not isinstance(runner, str) or runner not in _RUNNERS:
        return None
    tier = data.get("model_tier")
    model = data.get("cursor_model")
    rules = data.get("rules")
    return Profile(
        id=key,
        runner=runner,
        model_tier=tier if isinstance(tier, str) and tier in _TIERS else "local",
        blocks=_strings(data.get("blocks")),
        rules=rules if isinstance(rules, str) else "default",
        max_parallel=_whole(data.get("max_parallel"), 1),
        cursor_model=model if isinstance(model, str) else "",
    )


def _from_meta(meta: dict[str, object], body: str) -> Task:
    budget = _mapping(meta.get("budget"))
    used = _mapping(meta.get("used"))
    cursor = _mapping(meta.get("cursor"))
    status = meta.get("status")
    return Task(
        id=str(meta.get("id", "")),
        title=str(meta.get("title", "")),
        status=status if isinstance(status, str) and status in _SPEC else "backlog",
        agent=str(meta.get("agent", "spec-checker")),
        runner=str(meta.get("runner", "")),
        inputs=_strings(meta.get("inputs")),
        scope=_strings(meta.get("scope")),
        depends_on=_strings(meta.get("depends_on")),
        budget_tokens=_whole(budget.get("tokens"), 200000),
        budget_minutes=_whole(budget.get("minutes"), 20),
        used_tokens=_whole(used.get("tokens"), 0),
        used_minutes=_whole(used.get("minutes"), 0),
        created_by=str(meta.get("created_by", "")),
        body=body,
        proposals=_strings(meta.get("proposals")),
        progress=str(meta.get("progress", "")),
        question=str(meta.get("question", "")),
        blocked=str(meta.get("blocked", "")),
        cursor_agent_id=str(cursor.get("agent_id", "")),
        cursor_run_id=str(cursor.get("run_id", "")),
        cursor_url=str(cursor.get("url", "")),
    )


def _meta(task: Task) -> dict[str, object]:
    meta: dict[str, object] = {
        "agent": task.agent,
        "blocked": task.blocked,
        "budget": {"minutes": task.budget_minutes, "tokens": task.budget_tokens},
        "created_by": task.created_by,
        "depends_on": list(task.depends_on),
        "id": task.id,
        "inputs": list(task.inputs),
        "progress": task.progress,
        "proposals": list(task.proposals),
        "question": task.question,
        "runner": task.runner,
        "scope": list(task.scope),
        "status": task.status,
        "title": task.title,
        "used": {"minutes": task.used_minutes, "tokens": task.used_tokens},
    }
    if task.cursor_agent_id or task.cursor_run_id or task.cursor_url:
        meta["cursor"] = {
            "agent_id": task.cursor_agent_id,
            "run_id": task.cursor_run_id,
            "url": task.cursor_url,
        }
    return meta


def fresh(
    title: str,
    body: str,
    actor: str,
    depends_on: tuple[str, ...],
    chosen: Profile,
) -> Task:
    return Task(
        id=new_id(),
        title=title.strip(),
        status="backlog",
        agent=chosen.id,
        runner=chosen.runner,
        inputs=(),
        scope=(),
        depends_on=depends_on,
        budget_tokens=200000,
        budget_minutes=20,
        used_tokens=0,
        used_minutes=0,
        created_by=actor,
        body=body.strip(),
    )


def cast_host(value: object) -> Host:
    return cast(Host, value)
