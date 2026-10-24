"""Proposal list, one proposal, accept and reject."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from iterthink.services.bridge import Bridge, Conflict, ProposalInfo
from iterthink.web.app import actor_of, bridge_of
from iterthink.web.routes.history import diff_view, when, who
from iterthink.web.routes.home import render

router = APIRouter()
_bridge = Depends(bridge_of)
_actor = Depends(actor_of)
_reason = Form("")

_FITS = "This proposal no longer fits the current file"


def _proposal(bridge: Bridge, project_id: str, proposal_id: str) -> ProposalInfo:
    items = bridge.proposals(project_id, status=None)
    return next(item for item in items if item.id == proposal_id)


def _context(
    bridge: Bridge, project_id: str, proposal_id: str, toast: str, notice: str
) -> dict[str, object]:
    proposal = _proposal(bridge, project_id, proposal_id)
    views = [diff_view(item) for item in bridge.proposal_diff(project_id, proposal_id)]
    auto = getattr(bridge, "impact_auto", None)
    impact_auto = bool(auto(project_id, proposal_id)) if callable(auto) else False
    return {
        "project_id": project_id,
        "proposal": proposal,
        "views": views,
        "toast": toast,
        "notice": notice,
        "impact_auto": impact_auto,
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
