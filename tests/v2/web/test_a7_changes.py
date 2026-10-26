"""Per-change review: one fragment per change, posted on its own, 409 when stale."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from iterthink.services.bridge_fake import FakeBridge

MD = "Pflichtenheft.md"


def _propose_two(bridge: FakeBridge, project_id: str, project_dir: Path) -> str:
    text = (project_dir / MD).read_text("utf-8").replace("EI30", "EI60").replace("1.2 m", "1.5 m")
    return bridge.propose(project_id, {MD: text}, "agent:checker", "Türen und Fluchtwege").id


def _hash_of(html: str, change_id: str) -> str:
    match = re.search(rf'data-change-id="{change_id}" data-hash="([0-9a-f]*)"', html)
    assert match, f"no fragment for {change_id}"
    return match.group(1)


def test_change_fragment_posts_and_409_marks_outdated(
    client: TestClient, bridge: FakeBridge, project_id: str, project_dir: Path
) -> None:
    pid = _propose_two(bridge, project_id, project_dir)
    (diff,) = bridge.proposal_diff(project_id, pid)
    door, exits = (block.id for block in diff.blocks if block.kind != "stable")
    base = f"/p/{project_id}/proposals/{pid}/changes"

    page = client.get(f"/p/{project_id}/proposals/{pid}")
    candidate = _hash_of(page.text, door)
    assert candidate
    assert _hash_of(page.text, exits) == candidate
    assert f'action="{base}/{door}/accept"' in page.text
    assert "2 of 2 changes open" in page.text

    accepted = client.post(f"{base}/{door}/accept", data={"candidate": candidate})
    assert accepted.status_code == 200
    assert f'id="change-{door}"' in accepted.text
    assert 'data-status="accepted"' in accepted.text
    assert 'id="change-status" hx-swap-oob="true"' in accepted.text
    assert "1 of 2 changes open" in accepted.text
    assert "EI30" in (project_dir / MD).read_text("utf-8")

    edited = client.post(
        f"{base}/{exits}/edit", data={"candidate": candidate, "text": "Fluchtwege 1.8 m."}
    )
    assert edited.status_code == 200
    assert edited.headers["hx-retarget"] == "#main"
    info = next(item for item in bridge.proposals(project_id, None) if item.id == pid)
    assert info.candidate != candidate
    (new_exits,) = (key for key, state in info.changes.items() if state == "open")

    stale = client.post(f"{base}/{new_exits}/reject", data={"candidate": candidate})
    assert stale.status_code == 409
    assert 'class="change outdated"' in stale.text
    assert _hash_of(stale.text, new_exits) == info.candidate
    assert 'data-status="open"' in stale.text
    assert "EI30" in (project_dir / MD).read_text("utf-8")

    done = client.post(f"{base}/{new_exits}/accept", data={"candidate": info.candidate})
    assert done.status_code == 200
    assert "versions-changed" in done.headers["hx-trigger"]
    assert (project_dir / MD).read_text("utf-8") == (
        "# Pflichtenheft\n\nDie Türen im EG sind EI60.\n\nFluchtwege 1.8 m.\n"
    )
