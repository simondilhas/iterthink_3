"""Proposal list, one proposal, accept and reject, also one change at a time."""

from __future__ import annotations

import json
from collections.abc import Callable

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from iterthink.services.bridge import Block, Bridge, Conflict, FileDiff, NotFound, ProposalInfo
from iterthink.web.app import actor_of, bridge_of
from iterthink.web.routes.history import diff_view, when, who
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)
_actor = Depends(actor_of)
_reason = Form("")
_candidate = Form("")
_text = Form(...)

_FITS = "This proposal no longer fits the current file"
_OUTDATED = "This proposal changed meanwhile. Check the refreshed changes."


def _proposal(bridge: Bridge, project_id: str, proposal_id: str) -> ProposalInfo:
    items = bridge.proposals(project_id, status=None)
    return next(item for item in items if item.id == proposal_id)


def _change(index: int, block: Block, proposal: ProposalInfo) -> dict[str, object]:
    return {
        "index": index,
        "id": block.id,
        "kind": block.kind,
        "before": block.before,
        "after": block.after,
        "segments": block.segments,
        "status": proposal.changes.get(block.id, "open"),
    }


def _review_view(diff: FileDiff, proposal: ProposalInfo) -> dict[str, object]:
    view = diff_view(diff)
    if view["kind"] != "text" or proposal.status != "open" or not proposal.changes:
        return view
    blocks = [block for block in diff.blocks if block.kind != "stable"]
    view["changes"] = [_change(index, block, proposal) for index, block in enumerate(blocks)]
    view["decidable"] = True
    return view


def _context(
    bridge: Bridge, project_id: str, proposal_id: str, toast: str, notice: str
) -> dict[str, object]:
    proposal = _proposal(bridge, project_id, proposal_id)
    diffs = bridge.proposal_diff(project_id, proposal_id)
    views = [_review_view(item, proposal) for item in diffs]
    states = list(proposal.changes.values())
    auto = getattr(bridge, "impact_auto", None)
    impact_auto = bool(auto(project_id, proposal_id)) if callable(auto) else False
    return {
        "project_id": project_id,
        "proposal": proposal,
        "views": views,
        "toast": toast,
        "notice": notice,
        "impact_auto": impact_auto,
        "open_changes": states.count("open"),
        "total_changes": len(states),
        "who": who,
        "when": when,
    }


@router.get("/p/{project_id}/proposals", response_class=HTMLResponse, name="proposals")
def proposals_page(request: Request, project_id: str, bridge: Bridge = _bridge) -> HTMLResponse:
    return render(
        request,
        "review/page.html",
        project_id=project_id,
        proposals=bridge.proposals(project_id, status=None),
        who=who,
        when=when,
    )


@router.get("/p/{project_id}/proposals/{proposal_id}", response_class=HTMLResponse, name="proposal")
def proposal_page(
    request: Request, project_id: str, proposal_id: str, bridge: Bridge = _bridge
) -> HTMLResponse:
    context = _context(bridge, project_id, proposal_id, "", "")
    return render(request, "review/detail.html", **context)


def _triggers(path: str) -> str:
    return json.dumps({"versions-changed": {"path": path}, "proposals-changed": {}})


@router.post("/p/{project_id}/proposals/{proposal_id}/accept", name="accept", response_model=None)
def accept(
    request: Request,
    project_id: str,
    proposal_id: str,
    reason: str = _reason,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> HTMLResponse:
    notice = ""
    toast = "Accepted"
    try:
        bridge.accept(project_id, proposal_id, actor, reason)
    except Conflict:
        notice = _FITS
        toast = ""
    proposal = _proposal(bridge, project_id, proposal_id)
    context = _context(bridge, project_id, proposal_id, toast, notice)
    response = render(request, "review/body.html", **context)
    if notice:
        response.headers["HX-Trigger"] = json.dumps({"proposals-changed": {}})
    else:
        path = proposal.paths[0] if proposal.paths else ""
        response.headers["HX-Trigger"] = _triggers(path)
    return response


@router.post("/p/{project_id}/proposals/{proposal_id}/reject", name="reject", response_model=None)
def reject(
    request: Request,
    project_id: str,
    proposal_id: str,
    reason: str = _reason,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> HTMLResponse:
    bridge.reject(project_id, proposal_id, actor, reason)
    context = _context(bridge, project_id, proposal_id, "Rejected", "")
    response = render(request, "review/body.html", **context)
    response.headers["HX-Trigger"] = _triggers("")
    return response


def _find(views: object, change_id: str) -> dict[str, object] | None:
    for view in views if isinstance(views, list) else []:
        changes = view.get("changes") if view.get("decidable") else None
        for change in changes if isinstance(changes, list) else []:
            if isinstance(change, dict) and change.get("id") == change_id:
                return {str(key): value for key, value in change.items()}
    return None


def _body(request: Request, context: dict[str, object], status_code: int = 200) -> HTMLResponse:
    response = render(request, "review/body.html", **context)
    response.status_code = status_code
    response.headers["HX-Retarget"] = "#main"
    response.headers["HX-Reswap"] = "innerHTML"
    return response


def _changed(
    request: Request, bridge: Bridge, project_id: str, proposal_id: str, toast: str
) -> HTMLResponse:
    proposal = _proposal(bridge, project_id, proposal_id)
    context = _context(bridge, project_id, proposal_id, toast, "")
    response = _body(request, context)
    if proposal.status == "open":
        response.headers["HX-Trigger"] = json.dumps({"proposals-changed": {}})
    else:
        response.headers["HX-Trigger"] = _triggers(proposal.paths[0] if proposal.paths else "")
    return response


def _fragment(
    request: Request, context: dict[str, object], change_id: str, outdated: bool
) -> HTMLResponse:
    change = _find(context["views"], change_id)
    if change is None:
        notice = _OUTDATED if outdated else ""
        return _body(request, {**context, "notice": notice}, 409 if outdated else 200)
    response = render(
        request, "review/change_response.html", change=change, outdated=outdated, **context
    )
    response.status_code = 409 if outdated else 200
    return response


def _decide(
    request: Request,
    route: tuple[Bridge, str, str, str],
    call: Callable[[], ProposalInfo],
    candidate: str,
    toast: str,
    whole: bool = False,
) -> HTMLResponse:
    """Any edit re-renders every change: ids and the candidate move with it."""
    bridge, project_id, proposal_id, change_id = route
    try:
        info = call()
    except (Conflict, NotFound):
        current = _proposal(bridge, project_id, proposal_id)
        stale = bool(candidate) and candidate != current.candidate
        if current.status != "open" or not stale:
            notice = "" if current.status != "open" else _FITS
            return _body(request, _context(bridge, project_id, proposal_id, "", notice), 409)
        context = _context(bridge, project_id, proposal_id, "", "")
        return _fragment(request, context, change_id, outdated=True)
    if whole or info.status != "open":
        return _changed(request, bridge, project_id, proposal_id, toast)
    context = _context(bridge, project_id, proposal_id, toast, "")
    return _fragment(request, context, change_id, outdated=False)


_CHANGE = "/p/{project_id}/proposals/{proposal_id}/changes/{change_id}"


@router.post(_CHANGE + "/accept", name="accept_change", response_model=None)
def accept_change(
    request: Request,
    project_id: str,
    proposal_id: str,
    change_id: str,
    candidate: str = _candidate,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> HTMLResponse:
    def call() -> ProposalInfo:
        return bridge.decide_change(
            project_id, proposal_id, change_id, "accepted", actor, "", candidate or None
        )

    route = (bridge, project_id, proposal_id, change_id)
    return _decide(request, route, call, candidate, "Change accepted")


@router.post(_CHANGE + "/reject", name="reject_change", response_model=None)
def reject_change(
    request: Request,
    project_id: str,
    proposal_id: str,
    change_id: str,
    reason: str = _reason,
    candidate: str = _candidate,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> HTMLResponse:
    def call() -> ProposalInfo:
        return bridge.decide_change(
            project_id, proposal_id, change_id, "rejected", actor, reason, candidate or None
        )

    route = (bridge, project_id, proposal_id, change_id)
    return _decide(request, route, call, candidate, "Change rejected")


@router.post(_CHANGE + "/edit", name="edit_change", response_model=None)
def edit_change(
    request: Request,
    project_id: str,
    proposal_id: str,
    change_id: str,
    text: str = _text,
    candidate: str = _candidate,
    bridge: Bridge = _bridge,
    actor: str = _actor,
) -> HTMLResponse:
    def call() -> ProposalInfo:
        return bridge.edit_change(
            project_id, proposal_id, change_id, text, actor, candidate or None
        )

    route = (bridge, project_id, proposal_id, change_id)
    return _decide(request, route, call, candidate, "Change edited", whole=True)
