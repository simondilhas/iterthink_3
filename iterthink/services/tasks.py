"""Task board methods on the real bridge. Status words in the file are the spec's."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from iterthink.ai.cursor_agent import CursorClient
from iterthink.services.agent_runner import (
    apply_stream,
    claim,
    drop_claim,
    follow,
    handover,
    launch,
    note_usage,
    pool,
    set_remote,
    stop,
)
from iterthink.services.bridge import Conflict, Forbidden, Invalid, ProposalInfo, TaskInfo
from iterthink.services.task_store import (
    Host,
    Task,
    cast_host,
    fresh,
    in_scope,
    info,
    load,
    load_all,
    overlaps,
    profile,
    save,
)


class _Proposer(Protocol):
    def propose(
        self,
        project: str,
        changes: Mapping[str, str],
        actor: str,
        reason: str,
        baseline: str | None = None,
    ) -> ProposalInfo: ...


@dataclass(frozen=True)
class Card:
    """One board card. `status` is the spec word, not the contract word."""

    id: str
    title: str
    status: str
    progress: str
    question: str
    blocked: str
    url: str
    proposals: tuple[str, ...]
    overlap: str
    run_again: bool


class TasksBridge:
    """Real-bridge task methods. Today's contract methods plus the ones it still lacks."""

    def use_cursor(self, client: CursorClient) -> None:
        self._cursor_client = client

    def use_cursor_key(self, key: str) -> None:
        self._cursor_key = key

    def task_create(
        self, project: str, title: str, body: str, actor: str, depends_on: tuple[str, ...] = ()
    ) -> TaskInfo:
        if not title.strip():
            raise Invalid("a task needs a title")
        host = cast_host(self)
        root = host._root(project)
        task = fresh(title, body, actor, depends_on, profile(root, "spec-checker"))
        save(host, project, root, task, actor, "task_created", "created a task")
        return info(task)

    def task_start(self, project: str, task_id: str, actor: str) -> TaskInfo:
        host = cast_host(self)
        root = host._root(project)
        task = load(root, task_id)
        if task.status == "backlog":
            if not actor.startswith("user:"):
                raise Forbidden("only the user moves a task to ready")
            moved = handover(host, project, task, actor)
            if moved.status != "ready":
                return info(moved)
            if any(load(root, dep).status != "done" for dep in moved.depends_on):
                raise Conflict("dependency not done")
            return info(launch(host, project, moved, actor))
        return info(launch(host, project, task, actor))

    def tasks(self, project: str) -> list[TaskInfo]:
        host = cast_host(self)
        return [info(item) for item in load_all(host._root(project))]

    def task_ready(self, project: str, task_id: str, actor: str) -> TaskInfo:
        host = cast_host(self)
        return info(handover(host, project, load(host._root(project), task_id), actor))

    def task_configure(
        self,
        project: str,
        task_id: str,
        actor: str,
        *,
        agent: str | None = None,
        scope: tuple[str, ...] | None = None,
        budget: tuple[int, int] | None = None,
        inputs: tuple[str, ...] | None = None,
    ) -> TaskInfo:
        host = cast_host(self)
        root = host._root(project)
        task = load(root, task_id)
        _configure(task, root, agent, scope, budget, inputs)
        save(host, project, root, task, actor, "task_status", "updated a task")
        return info(load(root, task.id))

    def task_propose(
        self, project: str, task_id: str, changes: Mapping[str, str], actor: str, reason: str
    ) -> ProposalInfo:
        host = cast_host(self)
        root = host._root(project)
        task = load(root, task_id)
        _guard_write(root, task, changes)
        made = cast(_Proposer, self).propose(
            project, dict(changes), actor, f"{reason} (task {task.id})"
        )
        task.proposals = (*task.proposals, str(made.id))
        save(
            host,
            project,
            root,
            task,
            actor,
            "task_proposal",
            "linked a proposal",
            {"proposal": made.id},
        )
        return made

    def task_call(self, project: str, task_id: str, block: str, actor: str) -> str:
        del actor
        host = cast_host(self)
        chosen = profile(host._root(project), load(host._root(project), task_id).agent)
        if block not in chosen.blocks:
            raise Forbidden(f"this agent cannot {block}")
        return block

    def task_ask(self, project: str, task_id: str, question: str, actor: str) -> TaskInfo:
        return _ask(cast_host(self), project, task_id, question, actor)

    def task_answer(self, project: str, task_id: str, text: str, actor: str) -> TaskInfo:
        return _answer(cast_host(self), project, task_id, text, actor)

    def task_note_usage(self, project: str, task_id: str, tokens: int, minutes: int) -> TaskInfo:
        host = cast_host(self)
        root = host._root(project)
        return info(note_usage(host, project, load(root, task_id), tokens, minutes))

    def task_claim(self, project: str, task_id: str, actor: str, client: str) -> TaskInfo:
        host = cast_host(self)
        root = host._root(project)
        return info(claim(host, project, load(root, task_id), actor, client))

    def task_update(self, project: str, task_id: str, progress: str, actor: str) -> TaskInfo:
        host = cast_host(self)
        root = host._root(project)
        task = load(root, task_id)
        task.progress = progress
        save(host, project, root, task, actor, "task_progress", "updated task progress")
        return info(task)

    def task_complete(self, project: str, task_id: str, summary: str, actor: str) -> TaskInfo:
        return _finish(cast_host(self), project, task_id, summary, actor)

    def task_cancel(self, project: str, task_id: str, actor: str) -> TaskInfo:
        return _cancel(cast_host(self), project, task_id, actor)

    def task_run_again(self, project: str, task_id: str, actor: str) -> TaskInfo:
        return _again(cast_host(self), project, task_id, actor)

    def task_accept_delivery(self, project: str, task_id: str, actor: str) -> TaskInfo:
        return _deliver(cast_host(self), project, task_id, actor)

    def task_reject(self, project: str, task_id: str, actor: str, reason: str) -> TaskInfo:
        return _reject(cast_host(self), project, task_id, actor, reason)

    def task_apply_stream(self, project: str, task_id: str) -> TaskInfo:
        host = cast_host(self)
        root = host._root(project)
        return info(apply_stream(host, project, load(root, task_id)))

    def task_set_remote(self, project: str, url: str) -> None:
        set_remote(cast_host(self)._root(project), url)

    def task_board(self, project: str) -> list[Card]:
        host = cast_host(self)
        rows = load_all(host._root(project))
        states = _states(self, project)
        return [_card(task, rows, states) for task in rows]


def on_verdict(
    host: object, project: str, proposal_id: str, verdict: str, actor: str, reason: str
) -> None:
    """Accepted proposals finish the task. One rejection rejects it."""
    bridge = cast_host(host)
    root = bridge._root(project)
    for task in load_all(root):
        if proposal_id in task.proposals:
            _settle(bridge, project, task, verdict, actor, reason, _states(host, project))
            return


def _configure(
    task: Task,
    root: Path,
    agent: str | None,
    scope: tuple[str, ...] | None,
    budget: tuple[int, int] | None,
    inputs: tuple[str, ...] | None,
) -> None:
    if agent:
        task.agent = agent
        task.runner = profile(root, agent).runner
    if scope is not None:
        task.scope = scope
    if budget is not None:
        task.budget_tokens, task.budget_minutes = budget
    if inputs is not None:
        task.inputs = inputs


def _guard_write(root: Path, task: Task, changes: Mapping[str, str]) -> None:
    if "write" not in profile(root, task.agent).blocks:
        raise Forbidden("this agent cannot write")
    for path in changes:
        if not in_scope(task.scope, path):
            raise Forbidden(f"{path} is outside the task scope")


def _ask(host: Host, project: str, task_id: str, question: str, actor: str) -> TaskInfo:
    root = host._root(project)
    task = load(root, task_id)
    task.question = question.strip()
    task.status = "needs-input"
    task.body = f"{task.body.rstrip()}\n\n## Question\n\n{question.strip()}\n"
    save(host, project, root, task, actor, "task_asked", "asked a question")
    return info(task)


def _answer(host: Host, project: str, task_id: str, text: str, actor: str) -> TaskInfo:
    root = host._root(project)
    task = load(root, task_id)
    task.body = f"{task.body.rstrip()}\n\n## Answer\n\n{text.strip()}\n"
    task.question = ""
    if task.blocked != "budget reached" and task.status == "needs-input":
        task.status = "running"
    follow(host, project, task, text.strip(), actor)
    save(host, project, root, task, actor, "task_status", "answered a question")
    return info(task)


def _finish(host: Host, project: str, task_id: str, summary: str, actor: str) -> TaskInfo:
    root = host._root(project)
    task = load(root, task_id)
    task.body = f"{task.body.rstrip()}\n\n## Summary\n\n{summary.strip()}\n"
    task.status = "review"
    task.progress = summary.strip()[:80]
    drop_claim(host, root, task)
    save(host, project, root, task, actor, "task_completed", "finished a task")
    return info(task)


def _cancel(host: Host, project: str, task_id: str, actor: str) -> TaskInfo:
    root = host._root(project)
    task = load(root, task_id)
    stop(host, project, task)
    task.status = "cancelled"
    drop_claim(host, root, task)
    save(host, project, root, task, actor, "task_cancelled", "cancelled a task")
    return info(task)


def _again(host: Host, project: str, task_id: str, actor: str) -> TaskInfo:
    root = host._root(project)
    task = load(root, task_id)
    drop_claim(host, root, task)
    task.status = "ready"
    task.progress = ""
    save(host, project, root, task, actor, "task_handed_over", "run again on the new version")
    pool(host, project)
    return info(load(root, task.id))


def _deliver(host: Host, project: str, task_id: str, actor: str) -> TaskInfo:
    root = host._root(project)
    task = load(root, task_id)
    if task.status != "review":
        raise Conflict("the task is not in review")
    states = _states(host, project)
    if any(states.get(pid) in {"open", "conflict"} for pid in task.proposals):
        raise Conflict("proposals are still open")
    task.status = "done"
    drop_claim(host, root, task)
    save(host, project, root, task, actor, "task_completed", "accepted the delivery")
    return info(task)


def _reject(host: Host, project: str, task_id: str, actor: str, reason: str) -> TaskInfo:
    if not reason.strip():
        raise Invalid("rejecting needs a reason")
    root = host._root(project)
    task = load(root, task_id)
    task.status = "rejected"
    task.blocked = reason.strip()
    task.body = f"{task.body.rstrip()}\n\nRejected: {reason.strip()}\n"
    drop_claim(host, root, task)
    save(host, project, root, task, actor, "task_rejected", "rejected a task")
    return info(task)


def _settle(
    host: Host,
    project: str,
    task: Task,
    verdict: str,
    actor: str,
    reason: str,
    states: dict[str, str],
) -> None:
    root = host._root(project)
    if verdict == "rejected":
        task.status = "rejected"
        task.blocked = reason
        task.body = f"{task.body.rstrip()}\n\nRejected: {reason}\n"
        drop_claim(host, root, task)
        save(host, project, root, task, actor, "task_rejected", "rejected a task")
        return
    linked = [states[pid] for pid in task.proposals if pid in states]
    if linked and all(item == "accepted" for item in linked):
        task.status = "done"
        drop_claim(host, root, task)
        save(host, project, root, task, actor, "task_completed", "accepted the task")


def _states(host: object, project: str) -> dict[str, str]:
    method = getattr(host, "proposals", None)
    if not callable(method):
        return {}
    return {str(item.id): str(item.status) for item in method(project, None)}


def _card(task: Task, rows: list[Task], states: dict[str, str]) -> Card:
    names = [
        other.title
        for other in rows
        if other.id != task.id and task.scope and other.scope and overlaps(task.scope, other.scope)
    ]
    return Card(
        id=task.id,
        title=task.title,
        status=task.status,
        progress=task.progress,
        question=task.question,
        blocked=task.blocked,
        url=task.cursor_url,
        proposals=task.proposals,
        overlap=", ".join(names),
        run_again=any(states.get(pid) == "conflict" for pid in task.proposals),
    )
