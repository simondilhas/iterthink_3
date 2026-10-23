"""Opening a project checks the decision record and exports it."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from iterthink.services.bridge_real import RealBridge
from iterthink.services.event_log import append, checkpoint, read
from iterthink.services.proposals import CONTRACT
from iterthink.web.app import TOKEN_HEADER, create_app

MD = "Pflichtenheft.md"
TOKEN = "test-token"


def _bridge(tmp_path: Path, project_dir: Path) -> tuple[RealBridge, str]:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    return bridge, bridge.make_project(project_dir).id


def _other_log(project_dir: Path, project: str, egress: str) -> None:
    append(
        project_dir,
        machine="m-other",
        actor="user:other",
        type="settings",
        project=project,
        payload={"egress": egress},
        contract=CONTRACT,
    )


def test_break_found_on_open_shows_banner_and_logs(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    _other_log(project_dir, project, "shielded")
    checkpoint(
        project_dir, machine="m-test", actor="user:local", project=project, contract=CONTRACT
    )
    (project_dir / ".iterthink" / "log" / "m-other.jsonl").unlink()
    _other_log(project_dir, project, "none")
    app = create_app(bridge=bridge, token=TOKEN, actor="user:simon")
    client = TestClient(app, headers={TOKEN_HEADER: TOKEN, "accept": "text/html"})
    page = client.get(f"/p/{project}")
    assert page.status_code == 200
    assert "The decision record has a break at m-test line 2" in page.text
    events = list(read(project_dir / ".iterthink" / "log" / "m-test.jsonl"))
    audit = [event for event in events if event.type == "audit"]
    assert audit
    assert audit[-1].payload["machine"] == "m-test"
    assert audit[-1].payload["line"] == 2


def test_audit_export_resolves_blobs_and_writes_report(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    made = bridge.propose(project, {MD: "EI60\n"}, "agent:checker", "Brandschutz")
    bridge.reject(project, made.id, "user:simon", "EI30 reicht")
    bridge.handover(project, "full", tmp_path / "archive")
    folders = list((project_dir / ".iterthink" / "exports").glob("audit-*"))
    assert len(folders) == 1
    folder = folders[0]
    exported = (folder / "events.json").read_text(encoding="utf-8")
    assert "EI30 reicht" in exported
    assert "blob:" not in exported
    assert "EI30 reicht" in (folder / "events.csv").read_text(encoding="utf-8")
    report = (folder / "report.md").read_text(encoding="utf-8")
    assert MD in report
    assert "rejected" in report
    assert "tamper-evident" in report
    assert (folder / "verify_log.py").is_file()
