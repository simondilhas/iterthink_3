"""Proposal review: list, accept, reject, conflict."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from iterthink.services.bridge_fake import FakeBridge

_SPACE = re.compile(r"\s+")


def test_proposals_list_and_detail_show_reason_actor_diff(
    client: TestClient, bridge: FakeBridge, project_id: str
) -> None:
    info = bridge.propose(
        project_id, {"Pflichtenheft.md": "# Pflichtenheft\n\nNeu.\n"}, "agent:checker", "retitle"
    )
    listing = client.get(f"/p/{project_id}/proposals")
    assert "retitle" in listing.text
    assert "agent checker" in listing.text
    detail = client.get(f"/p/{project_id}/proposals/{info.id}")
    assert "retitle" in detail.text
    assert "agent checker" in detail.text
    assert 'class="change"' in detail.text
    assert "<ins>" in detail.text or "Neu." in detail.text
    assert 'name="reason"' in detail.text
    assert "Accept" in detail.text
    assert "Reject" in detail.text


def test_accept_applies_and_triggers_refresh(
    client: TestClient, bridge: FakeBridge, project_id: str, project_dir: Path
) -> None:
    info = bridge.propose(
        project_id, {"Pflichtenheft.md": "# Pflichtenheft\n\nNeu.\n"}, "user:simon", "retitle"
    )
    page = client.post(f"/p/{project_id}/proposals/{info.id}/accept", data={"reason": ""})
    assert page.status_code == 200
    assert "Accepted" in page.text
    trigger = page.headers["hx-trigger"]
    assert "versions-changed" in trigger
    assert "proposals-changed" in trigger
    assert "Neu." in (project_dir / "Pflichtenheft.md").read_text(encoding="utf-8")


def test_reject_requires_reason(client: TestClient, bridge: FakeBridge, project_id: str) -> None:
    info = bridge.propose(project_id, {"Pflichtenheft.md": "Neu\n"}, "user:simon", "retitle")
    page = client.post(f"/p/{project_id}/proposals/{info.id}/reject", data={"reason": " "})
    assert page.status_code == 422
    assert "reason" in page.text.lower()


def test_reject_with_reason(
    client: TestClient, bridge: FakeBridge, project_id: str, project_dir: Path
) -> None:
    original = (project_dir / "Pflichtenheft.md").read_text(encoding="utf-8")
    info = bridge.propose(project_id, {"Pflichtenheft.md": "Neu\n"}, "user:simon", "retitle")
    page = client.post(
        f"/p/{project_id}/proposals/{info.id}/reject", data={"reason": "not this one"}
    )
    assert page.status_code == 200
    assert "Rejected" in page.text
    assert "proposals-changed" in page.headers["hx-trigger"]
    assert (project_dir / "Pflichtenheft.md").read_text(encoding="utf-8") == original


def test_accept_after_conflicting_edit_shows_conflict_message(
    client: TestClient, bridge: FakeBridge, project_id: str
) -> None:
    info = bridge.propose(
        project_id, {"Pflichtenheft.md": "From the proposal\n"}, "user:simon", "retitle"
    )
    client.post(f"/p/{project_id}/f/Pflichtenheft.md", data={"text": "Edited since\n"})
    page = client.post(f"/p/{project_id}/proposals/{info.id}/accept", data={"reason": ""})
    assert page.status_code == 200
    assert "This proposal no longer fits the current file" in page.text
    assert "conflict" in page.text


def test_diff_table_fragment_golden(
    client: TestClient, bridge: FakeBridge, project_id: str
) -> None:
    info = bridge.propose(
        project_id,
        {"Türliste.csv": "id,geschoss,typ,brandschutz\nT01,EG,Holz,EI90\nT03,OG,Stahl,EI30\n"},
        "user:simon",
        "revise the door list",
    )
    page = client.get(f"/p/{project_id}/proposals/{info.id}")
    start = page.text.index('<div id="diff">')
    fragment = page.text[start : page.text.index("</div>", start) + len("</div>")]
    expected = Path("tests/v2/golden/fragments/doors-table.html").read_text(encoding="utf-8")
    assert _SPACE.sub(" ", fragment).strip() == _SPACE.sub(" ", expected).strip()
