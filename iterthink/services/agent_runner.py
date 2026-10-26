"""Start ready tasks on a local runner or a Cursor cloud agent. Claude waits."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import cast

import keyring
from keyring.errors import KeyringError

from iterthink.ai.cursor_agent import CursorClient, CursorError, HttpxCursor
from iterthink.services.bridge import Conflict, Forbidden, Invalid
from iterthink.services.claims import Claimed, acquire, holder, release
from iterthink.services.egress import Tier, check
from iterthink.services.projects import settings_of, write_yaml
from iterthink.services.settings import get, load_yaml
from iterthink.services.task_store import (
    Host,
    Profile,
    Task,
    load,
    load_all,
    path_of,
    profile,
    save,
)

_KEY = "cursor.api_key"


def handover(host: Host, project: str, task: Task, actor: str) -> Task:
    """User moves Backlog to Ready, then the pool may start it."""
    if not actor.startswith("user:"):
        raise Forbidden("only the user moves a task to ready")
    if task.status != "backlog":
        raise Conflict(f"a task that is {task.status} is not in the backlog")
    root = host._root(project)
    chosen = profile(root, task.agent)
    task.runner = chosen.runner
    task.status = "ready"
    save(host, project, root, task, actor, "task_handed_over", "handed a task to ready")
    pool(host, project)
    return load(root, task.id)


def launch(host: Host, project: str, task: Task, actor: str) -> Task:
    """Start a Ready task. A live claim or an open dependency refuses."""
    root = host._root(project)
    current = load(root, task.id)
    if current.status == "running" and holder(root, path_of(current.id)) is not None:
        raise Conflict("this task is already running")
    if current.status != "ready":
        raise Conflict(f"cannot start a task that is {current.status}")
    if not _deps_done(root, current):
        raise Conflict("dependency not done")
    if not actor.strip():
        raise Invalid("missing actor")
    _begin(host, project, current, f"agent:{profile(root, current.agent).id}")
    return load(root, current.id)


def pool(host: Host, project: str) -> None:
    """Start ready local and cursor tasks whose dependencies are done, up to the limits."""
    root = host._root(project)
    for task in load_all(root):
        if task.status != "ready" or not _deps_done(root, task):
            continue
        chosen = profile(root, task.agent)
        if chosen.runner == "claude" or not _room(root, chosen):
            continue
        try:
            _begin(host, project, task, f"agent:{chosen.id}")
        except Conflict:
            continue


def note_usage(host: Host, project: str, task: Task, tokens: int, minutes: int) -> Task:
    """Add usage. Over budget cancels a Cursor run, then asks for input."""
    root = host._root(project)
    task.used_tokens += tokens
    task.used_minutes += minutes
    if task.used_tokens <= task.budget_tokens and task.used_minutes <= task.budget_minutes:
        save(host, project, root, task, f"agent:{task.agent}", "task_status", "recorded usage")
        return load(root, task.id)
    if task.runner == "cursor" and task.cursor_agent_id and task.cursor_run_id:
        _cursor(host).cancel(task.cursor_agent_id, task.cursor_run_id, _cursor_key(host))
    task.status = "needs-input"
    task.blocked = "budget reached"
    task.body = f"{task.body.rstrip()}\n\nbudget reached\n"
    save(host, project, root, task, f"agent:{task.agent}", "task_budget", "budget reached")
    return load(root, task.id)


def claim(host: Host, project: str, task: Task, actor: str, client: str) -> Task:
    """Claude Code claims a ready task. Nothing is launched here."""
    root = host._root(project)
    chosen = profile(root, task.agent)
    if chosen.runner != "claude":
        raise Forbidden("only a claude profile is claimed over MCP")
    if task.status != "ready":
        raise Conflict(f"cannot claim a task that is {task.status}")
    if not _deps_done(root, task):
        raise Conflict("dependency not done")
    running = [
        item for item in load_all(root) if item.status == "running" and item.agent == chosen.id
    ]
    if len(running) >= chosen.max_parallel:
        raise Conflict("parallel limit")
    _take(root, task, host.machine, f"claude:{client}")
    task.status = "running"
    task.runner = "claude"
    task.progress = "claimed"
    save(host, project, root, task, actor, "task_claimed", "claimed a task", {"client": client})
    return load(root, task.id)


def follow(host: Host, project: str, task: Task, text: str, actor: str) -> None:
    """Send a card answer to the open Cursor agent."""
    if task.runner != "cursor" or not task.cursor_agent_id:
        return
    _cursor(host).follow_up(task.cursor_agent_id, text, _cursor_key(host))


def stop(host: Host, project: str, task: Task) -> None:
    """Cancel the Cursor run when one is stored. The claim is dropped by the caller."""
    if task.runner == "cursor" and task.cursor_agent_id and task.cursor_run_id:
        _cursor(host).cancel(task.cursor_agent_id, task.cursor_run_id, _cursor_key(host))


def apply_stream(host: Host, project: str, task: Task) -> Task:
    """Step text from the run stream. FINISHED moves the card to Review."""
    root = host._root(project)
    if not task.cursor_agent_id or not task.cursor_run_id:
        raise Conflict("this task has no cursor run")
    events = _stream(host, task)
    for event in events:
        text = event.get("text", "")
        status = event.get("status", "")
        if text:
            task.progress = text
        elif status and status != "FINISHED":
            task.progress = status
        if status == "FINISHED" or event.get("type") == "finished":
            task.status = "review"
    if task.status == "review":
        drop_claim(host, root, task)
    actor = f"agent:{task.agent}"
    save(host, project, root, task, actor, "task_status", "updated task progress")
    return load(root, task.id)


def drop_claim(host: Host, root: Path, task: Task) -> None:
    current = holder(root, path_of(task.id))
    if current is not None and current.machine == host.machine:
        release(root, current)


def set_remote(root: Path, url: str) -> None:
    write_yaml(root / ".iterthink" / "settings" / "remote.yaml", {"url": url})


def remote_of(root: Path) -> str:
    url = load_yaml(root, "remote.yaml").get("url")
    return url if isinstance(url, str) else ""


def _begin(host: Host, project: str, task: Task, actor: str) -> None:
    root = host._root(project)
    chosen = profile(root, task.agent)
    task.runner = chosen.runner
    if chosen.runner == "cursor":
        _cursor_begin(host, project, task, chosen, actor)
        return
    if chosen.runner == "claude":
        return
    _local_begin(host, project, task, chosen, actor)


def _local_begin(host: Host, project: str, task: Task, chosen: Profile, actor: str) -> None:
    root = host._root(project)
    if check(root, "agent", _tier(chosen.model_tier)) == "deny":
        _block(host, project, task, actor, "egress blocks the agent")
        return
    _take(root, task, host.machine, "local")
    task.status = "running"
    task.progress = "running"
    save(host, project, root, task, actor, "task_launched", "started a local agent")


def _cursor_begin(host: Host, project: str, task: Task, chosen: Profile, actor: str) -> None:
    root = host._root(project)
    reason = _cursor_block(root)
    if reason:
        _block(host, project, task, actor, reason)
        return
    key = _cursor_key(host)
    if not key:
        _block(host, project, task, actor, "cursor key missing")
        return
    agent_id = task.cursor_agent_id or f"agent-{secrets.token_hex(4)}"
    task.cursor_agent_id = agent_id
    save(host, project, root, task, actor, "task_status", "stored the cursor agent id")
    _take(root, task, host.machine, f"cursor:{agent_id}")
    result = _open_agent(host, task, chosen, agent_id, key, remote_of(root))
    task.cursor_run_id = result.get("run_id", task.cursor_run_id)
    task.cursor_url = result.get("url", task.cursor_url)
    task.status = "running"
    task.progress = "launched"
    save(
        host,
        project,
        root,
        task,
        actor,
        "task_launched",
        "launched a cursor agent",
        {"agent_id": task.cursor_agent_id, "run_id": task.cursor_run_id},
    )


def _open_agent(
    host: Host, task: Task, chosen: Profile, agent_id: str, key: str, remote: str
) -> dict[str, str]:
    prompt = f"{task.title}\n\n{task.body.strip()}"
    created = _cursor(host).create_agent(
        agent_id, prompt, remote, chosen.cursor_model, key, auto_pr=False
    )
    if created.get("error") == "already exists":
        return _cursor(host).load_agent(agent_id, key)
    return created


def _cursor_block(root: Path) -> str:
    mode = settings_of(root).get("egress", "shielded")
    if mode != "allowed":
        return "egress must be allowed"
    if not remote_of(root):
        return "this project has no remote"
    return ""


def _block(host: Host, project: str, task: Task, actor: str, reason: str) -> None:
    root = host._root(project)
    task.status = "needs-input"
    task.blocked = reason
    task.body = f"{task.body.rstrip()}\n\n{reason}\n"
    save(host, project, root, task, actor, "task_asked", reason)


def _stream(host: Host, task: Task) -> list[dict[str, str]]:
    client = _cursor(host)
    key = _cursor_key(host)
    try:
        return client.stream(task.cursor_agent_id, task.cursor_run_id, key)
    except CursorError:
        view = client.get_run(task.cursor_agent_id, task.cursor_run_id, key)
        return [{"status": view.get("status", ""), "text": view.get("text", ""), "type": "status"}]


def _take(root: Path, task: Task, machine: str, user: str) -> None:
    try:
        acquire(root, path_of(task.id), machine=machine, user=user)
    except Claimed as exc:
        raise Conflict("this task is already running") from exc


def _deps_done(root: Path, task: Task) -> bool:
    return all(load(root, dep).status == "done" for dep in task.depends_on)


def _room(root: Path, chosen: Profile) -> bool:
    running = [item for item in load_all(root) if item.status == "running"]
    if len(running) >= _limit(root, "runner.max_parallel"):
        return False
    same = [item for item in running if item.agent == chosen.id]
    if len(same) >= chosen.max_parallel:
        return False
    tier = chosen.model_tier
    mates = [item for item in running if profile(root, item.agent).model_tier == tier]
    key = "runner.max_parallel_local" if tier == "local" else "runner.max_parallel_cloud"
    return len(mates) < _limit(root, key)


def _limit(root: Path, key: str) -> int:
    value = get(root, key).value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 1


def _tier(value: str) -> Tier:
    if value == "company":
        return "company"
    if value == "cloud":
        return "cloud"
    return "local"


def _cursor(host: Host) -> CursorClient:
    found = getattr(host, "_cursor_client", None)
    if found is not None:
        return cast(CursorClient, found)
    return HttpxCursor()


def _cursor_key(host: Host) -> str:
    stored = getattr(host, "_cursor_key", None)
    if isinstance(stored, str):
        return stored
    try:
        found = keyring.get_password("iterthink", _KEY)
    except KeyringError:
        return ""
    return found or ""
