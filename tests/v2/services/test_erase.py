"""Erased content leaves history. The decision record stays verifiable."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from iterthink.persistence.snapshots import Snapshots
from iterthink.services.bridge import Invalid
from iterthink.services.bridge_real import RealBridge
from iterthink.services.event_log import read
from iterthink.web.app import TOKEN_HEADER, create_app

SECRET = "PERSONAL-756.1234.5678.97"
PATH = "upload.md"
TOKEN = "erase-token"


def _bridge(tmp_path: Path, project_dir: Path) -> tuple[RealBridge, str]:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    return bridge, bridge.make_project(project_dir).id


def _secret_version(bridge: RealBridge, project: str) -> str:
    made = bridge.save(project, PATH, SECRET + "\n", "user:simon", "uploaded")
    assert made is not None
    later = bridge.save(project, PATH, "public note\n", "user:simon", "replaced")
    assert later is not None
    return made.id


def _objects(project_dir: Path) -> bytes:
    folder = project_dir / ".iterthink" / "versions" / "objects"
    if not folder.is_dir():
        return b""
    return b"".join(path.read_bytes() for path in folder.iterdir() if path.is_file())


def _verify_bundle(bundle: Path) -> subprocess.CompletedProcess[str]:
    script = bundle / "verification" / "verify_log.py"
    return subprocess.run(
        [sys.executable, "-I", str(script), str(bundle / "verification")],
        check=False,
        capture_output=True,
        text=True,
    )


def test_erased_content_unreachable_in_history(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    version = _secret_version(bridge, project)
    snaps = Snapshots(project_dir)
    assert SECRET.encode() in (snaps.file_at(version, PATH) or b"")
    bridge.erase(project, [version], "personal data", True, "user:simon")
    assert version not in {item.id for item in snaps.history()}
    assert snaps.file_at(version, PATH) is None
    assert SECRET.encode() not in _objects(project_dir)
    assert b"public note" in (snaps.file_at(snaps.head().id, PATH) or b"")
    digest = hashlib.sha256((SECRET + "\n").encode()).hexdigest()
    restored = project_dir / ".iterthink" / "versions" / "objects" / digest
    restored.write_bytes((SECRET + "\n").encode())
    snaps.history()
    assert not restored.exists()


def test_log_still_verifies_after_erase(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    version = _secret_version(bridge, project)
    target = tmp_path / "client"
    bridge.handover(project, "client", target)
    bridge.erase(project, [version], "personal data", True, "user:simon")
    assert bridge.verify(project).ok
    result = _verify_bundle(target)
    assert result.returncode == 0, result.stderr


def _proposal_parts(project_dir: Path, proposal: str) -> tuple[str, Path]:
    log = project_dir / ".iterthink" / "log" / "m-test.jsonl"
    for event in read(log):
        if event.type != "proposal_created" or event.payload.get("id") != proposal:
            continue
        ref = str(event.payload["reason"])
        blob = project_dir / ".iterthink" / "blobs" / ref.removeprefix("blob:")
        return str(event.payload["draft"]), blob
    raise AssertionError(proposal)


def test_erase_event_has_no_content(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    version = _secret_version(bridge, project)
    proposed = bridge.propose(project, {PATH: SECRET + "\n"}, "user:simon", "hide this")
    draft, blob = _proposal_parts(project_dir, proposed.id)
    assert blob.is_file()
    bridge.erase(project, [version, draft], "personal data", True, "user:simon")
    log = project_dir / ".iterthink" / "log" / "m-test.jsonl"
    assert SECRET not in log.read_text(encoding="utf-8")
    event = next(item for item in read(log) if item.type == "erase")
    body = json.dumps(event.payload)
    assert SECRET not in body
    assert PATH not in body
    assert event.payload["reason"] == "personal data"
    assert event.payload["versions"] == sorted([version, draft])
    digest = hashlib.sha256(PATH.encode()).hexdigest()
    assert digest in event.payload["path_hash"]
    assert not blob.exists()


def test_erase_requires_reason_and_confirmation(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    version = _secret_version(bridge, project)
    snaps = Snapshots(project_dir)
    kept = snaps.file_at(version, PATH)
    with pytest.raises(Invalid):
        bridge.erase(project, [version], "  ", True, "user:simon")
    with pytest.raises(Invalid):
        bridge.erase(project, [version], "personal data", False, "user:simon")
    assert snaps.file_at(version, PATH) == kept
    client = TestClient(
        create_app(bridge=bridge, token=TOKEN, actor="user:simon"),
        headers={TOKEN_HEADER: TOKEN, "accept": "text/html"},
    )
    review = client.post(
        f"/p/{project}/erase", data={"version": version, "reason": "personal data"}
    )
    assert review.status_code == 200
    assert "cannot be undone" in review.text
    assert SECRET not in review.text
    assert snaps.file_at(version, PATH) == kept
    missing = client.post(
        f"/p/{project}/erase", data={"version": version, "reason": "  ", "confirm": "yes"}
    )
    assert missing.status_code == 422
    assert snaps.file_at(version, PATH) == kept
    done = client.post(
        f"/p/{project}/erase",
        data={"version": version, "reason": "personal data", "confirm": "yes"},
    )
    assert done.status_code == 200
    assert snaps.file_at(version, PATH) is None
