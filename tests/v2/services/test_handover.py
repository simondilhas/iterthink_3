"""Full and client handover, and a bundle the client can verify alone."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from iterthink.persistence.snapshots import Snapshots
from iterthink.services.bridge_real import RealBridge
from iterthink.services.event_log import read

MD = "Pflichtenheft.md"


def _bridge(tmp_path: Path, project_dir: Path) -> tuple[RealBridge, str]:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    return bridge, bridge.make_project(project_dir).id


def _hide(project_dir: Path, name: str, text: str) -> None:
    folder = project_dir / ".iterthink" / name
    folder.mkdir(parents=True)
    (folder / "secret.txt").write_text(text, encoding="utf-8")


def _client(tmp_path: Path, project_dir: Path) -> tuple[RealBridge, str, Path]:
    bridge, project = _bridge(tmp_path, project_dir)
    body = "REJECTED-BODY-9f3a\n"
    made = bridge.propose(project, {MD: body}, "agent:checker", "change it")
    bridge.reject(project, made.id, "user:simon", "no")
    _hide(project_dir, "chats", "chat secret")
    _hide(project_dir, "apps", "app secret")
    _hide(project_dir, "prompts", "prompt secret")
    _hide(project_dir, "transcripts", "transcript secret")
    exports = project_dir / ".iterthink" / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    (exports / "door.csv").write_text("id,note\n", encoding="utf-8")
    return bridge, project, tmp_path / "client"


def _verify(bundle: Path) -> subprocess.CompletedProcess[str]:
    script = bundle / "verification" / "verify_log.py"
    return subprocess.run(
        [sys.executable, "-I", str(script), str(bundle / "verification")],
        check=False,
        capture_output=True,
        text=True,
    )


def test_client_handover_excludes_internal_material(tmp_path: Path, project_dir: Path) -> None:
    bridge, project, target = _client(tmp_path, project_dir)
    bridge.handover(project, "client", target)
    assert (target / MD).is_file()
    assert (target / ".iterthink" / "exports" / "door.csv").is_file()
    for name in ("chats", "apps", "prompts", "transcripts", "versions", "log", "blobs"):
        assert not (target / ".iterthink" / name).exists()
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in target.rglob("*")
        if path.is_file()
    )
    assert "chat secret" not in text
    assert "app secret" not in text
    assert "prompt secret" not in text
    assert "transcript secret" not in text
    assert "REJECTED-BODY-9f3a" not in text


def test_client_can_verify_with_stdlib_only(tmp_path: Path, project_dir: Path) -> None:
    bridge, project, target = _client(tmp_path, project_dir)
    bridge.handover(project, "client", target)
    result = _verify(target)
    assert result.returncode == 0, result.stderr


def test_tampered_bundle_fails_verification(tmp_path: Path, project_dir: Path) -> None:
    bridge, project, target = _client(tmp_path, project_dir)
    bridge.handover(project, "client", target)
    log = next((target / "verification").rglob("*.jsonl"))
    raw = bytearray(log.read_bytes())
    raw[10] ^= 1
    log.write_bytes(bytes(raw))
    result = _verify(target)
    assert result.returncode == 1


def test_handover_event_records_head_hashes(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    target = tmp_path / "archive"
    bridge.handover(project, "full", target)
    events = list(read(project_dir / ".iterthink" / "log" / "m-test.jsonl"))
    event = next(item for item in events if item.type == "handover")
    heads = event.payload["heads"]
    assert isinstance(heads, dict)
    recorded = heads["m-test"]
    assert isinstance(recorded, dict)
    assert recorded["hash"] == event.prev_hash
    assert recorded["seq"] == event.seq - 1
    assert event.payload["snapshot"] == Snapshots(project_dir).head().id
    assert (target / ".iterthink" / "log" / "m-test.jsonl").is_file()
    assert (target / ".iterthink" / "exports").is_dir()
