"""Rules accept a narrow change on their own, or refuse a path outright."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from iterthink.compare.change_classes import CHANGE_CLASSES, classify
from iterthink.services.agent_rules import Rules, decide, load
from iterthink.services.bridge import FileDiff, Forbidden, Invalid
from iterthink.services.bridge_real import RealBridge
from iterthink.services.event_log import Event, read_all
from iterthink.web.app import TOKEN_HEADER, create_app

TOKEN = "test-token"
_RULE = "**/*.md:typos"


def _bridge(tmp_path: Path) -> RealBridge:
    return RealBridge(state_dir=tmp_path / "state", machine="m-test")


def _rules(project: Path, text: str) -> None:
    folder = project / ".iterthink" / "settings"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "rules.yaml").write_text(text, encoding="utf-8")


def _direct(project: Path) -> None:
    _rules(
        project,
        "agents:\n  default: propose\n  direct:\n    - '**/*.md:typos'\n"
        "  deny: []\n  propose_always:\n    - '**/*.ifc'\n    - '**/*.csv'\n"
        "deletions: propose\n",
    )


def _events(project: Path, kind: str) -> list[Event]:
    return [event for event in read_all(project) if event.type == kind]


def test_spelling_fix_auto_accepted_under_rule(tmp_path: Path, project_dir: Path) -> None:
    _direct(project_dir)
    (project_dir / "notes.md").write_text("This is teh door.\n", encoding="utf-8")
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    made = bridge.propose(project, {"notes.md": "This is the door.\n"}, "agent:checker", "spelling")
    assert made.status == "accepted"
    assert made.decided_by == f"rule:{_RULE}"
    assert (project_dir / "notes.md").read_text(encoding="utf-8") == "This is the door.\n"
    verdicts = _events(project_dir, "verdict")
    assert verdicts[-1].payload.get("auto") is True
    assert verdicts[-1].actor == f"rule:{_RULE}"


def test_mixed_change_waits_for_human(tmp_path: Path, project_dir: Path) -> None:
    _direct(project_dir)
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    original = (project_dir / "Pflichtenheft.md").read_text(encoding="utf-8")
    made = bridge.propose(
        project, {"Pflichtenheft.md": original.replace("EI30", "EI90")}, "ai:margin", "rating"
    )
    assert made.status == "open"
    assert made.decided_by is None
    assert "EI30" in (project_dir / "Pflichtenheft.md").read_text(encoding="utf-8")


def test_rule_limited_to_paths(tmp_path: Path, project_dir: Path) -> None:
    _direct(project_dir)
    (project_dir / "notes.md").write_text("teh\n", encoding="utf-8")
    (project_dir / "notes.txt").write_text("teh\n", encoding="utf-8")
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    kept = bridge.propose(project, {"notes.md": "the\n"}, "app:door", "spelling")
    waiting = bridge.propose(project, {"notes.txt": "the\n"}, "app:door", "spelling")
    assert kept.status == "accepted"
    assert waiting.status == "open"
    assert (project_dir / "notes.txt").read_text(encoding="utf-8") == "teh\n"


def test_deny_refuses_and_logs_without_proposal(tmp_path: Path, project_dir: Path) -> None:
    _rules(
        project_dir,
        "agents:\n  default: propose\n  direct: []\n  deny:\n    - 'contracts/**'\n"
        "  propose_always: []\ndeletions: propose\n",
    )
    (project_dir / "contracts").mkdir()
    (project_dir / "contracts" / "a.md").write_text("keep\n", encoding="utf-8")
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    with pytest.raises(Forbidden):
        bridge.propose(project, {"contracts/a.md": "changed\n"}, "agent:checker", "edit")
    assert bridge.proposals(project, None) == []
    denied = _events(project_dir, "rule_denied")
    assert denied[-1].payload.get("rule") == "contracts/**"
    assert (project_dir / "contracts" / "a.md").read_text(encoding="utf-8") == "keep\n"


@pytest.mark.parametrize(
    ("path", "deletion"),
    [("note.md", True), ("model.ifc", False), ("plan.pdf", False), ("table.csv", False)],
)
def test_direct_never_applies_to_deletions_ifc_plans_or_propose_always(
    path: str, deletion: bool
) -> None:
    rules = Rules(
        default="propose",
        direct=("**/*:typos", "**/*.csv:csv_format"),
        deny=(),
        propose_always=("**/*.csv", "**/*.ifc"),
        deletions="propose",
    )
    choice = decide(rules, "agent:checker", path, FileDiff(path, "text", "changed"), deletion)
    assert choice.action == "propose"


def test_default_direct_is_refused(tmp_path: Path, project_dir: Path) -> None:
    _rules(project_dir, "agents:\n  default: direct\n  direct: []\ndeletions: propose\n")
    with pytest.raises(Invalid):
        load(project_dir)


def test_user_saves_are_never_ruled(tmp_path: Path, project_dir: Path) -> None:
    _rules(
        project_dir,
        "agents:\n  default: deny\n  direct:\n    - '**/*.md:typos'\n  deny:\n    - '**'\n"
        "  propose_always: []\ndeletions: deny\n",
    )
    (project_dir / "notes.md").write_text("teh\n", encoding="utf-8")
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    bridge.save(project, "notes.md", "the\n", "user:ada", "fix")
    assert (project_dir / "notes.md").read_text(encoding="utf-8") == "the\n"
    made = bridge.propose(project, {"notes.md": "teh door\n"}, "user:ada", "again")
    assert made.status == "open"
    assert _events(project_dir, "rule_denied") == []


def test_workspace_rules_inherited_by_project(
    tmp_path: Path, workspace_dir: Path, project_dir: Path
) -> None:
    folder = workspace_dir / ".iterthink" / "settings"
    folder.mkdir(parents=True)
    (folder / "rules.yaml").write_text(
        "agents:\n  default: propose\n  direct:\n    - '**/*.md:typos'\n",
        encoding="utf-8",
    )
    (project_dir / "notes.md").write_text("teh\n", encoding="utf-8")
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    made = bridge.propose(project, {"notes.md": "the\n"}, "agent:checker", "spelling")
    assert made.status == "accepted"
    assert made.decided_by == f"rule:{_RULE}"


def test_edges_typography_csv_deletion_and_default_deny(tmp_path: Path, project_dir: Path) -> None:
    curly = "It\u2019s fine.\n"
    assert "typography" in classify("a.md", b"It's fine.\n", curly.encode())
    plain = b"id,name\n1,hello\n"
    quoted = b'id,name\n1,"hello"\n'
    assert classify("t.csv", plain, quoted) == frozenset({"csv_format"})
    rules = Rules("propose", ("**/*.md:typos",), (), (), "deny")
    choice = decide(rules, "agent:a", "note.md", FileDiff("note.md", "text", "x"), True)
    assert choice.action == "deny"
    _direct(project_dir)
    (project_dir / "notes.md").write_text("teh\n", encoding="utf-8")
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    waiting = bridge.propose(project, {"notes.md": ""}, "agent:checker", "remove")
    assert waiting.status == "open"
    assert (project_dir / "notes.md").read_text(encoding="utf-8") == "teh\n"
    _rules(project_dir, "agents:\n  default: deny\n  direct: []\ndeletions: propose\n")
    with pytest.raises(Forbidden):
        bridge.propose(project, {"notes.md": "nope\n"}, "agent:checker", "no")


def test_auto_verdict_logged_with_rule_id_and_undo_restores(
    tmp_path: Path, project_dir: Path
) -> None:
    _direct(project_dir)
    (project_dir / "notes.md").write_text("teh\n", encoding="utf-8")
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    made = bridge.propose(project, {"notes.md": "the\n"}, "agent:checker", "spelling")
    verdict = _events(project_dir, "verdict")[-1]
    assert verdict.payload.get("auto") is True
    assert "typos" in str(verdict.actor)
    bridge.restore(project, "notes.md", made.baseline, "user:ada")
    assert (project_dir / "notes.md").read_text(encoding="utf-8") == "teh\n"
    restored = _events(project_dir, "restore")[-1]
    assert restored.actor == "user:ada"
    app = create_app(bridge=bridge, token=TOKEN, actor="user:ada")
    page = TestClient(app, headers={TOKEN_HEADER: TOKEN}).get(f"/p/{project}/proposals/{made.id}")
    assert page.status_code == 200
    assert "auto · rule **/*.md:typos" in page.text
    assert "Undo" in page.text
    assert "typos" in CHANGE_CLASSES
    assert "spelling" in classify("notes.md", b"teh\n", b"the\n")
