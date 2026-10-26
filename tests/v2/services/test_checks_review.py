"""Inherited checks are advice. They do not change a file or decide."""

from __future__ import annotations

from pathlib import Path

from iterthink.services.bridge_real import RealBridge
from iterthink.services.event_log import read_all


class _Model:
    def __init__(self, text: str, tier: str = "local") -> None:
        self.text = text
        self.tier = tier
        self.calls: list[str] = []

    def complete(self, system: str, user: str, tier: str) -> str:
        self.calls.append(tier)
        assert system
        assert user
        return self.text


def _bridge(tmp_path: Path) -> RealBridge:
    return RealBridge(state_dir=tmp_path / "state", machine="m-test")


def _write_checks(folder: Path, ident: str, label: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    text = (
        "checks:\n"
        f"  - id: {ident}\n"
        f"    label: {label}\n"
        "    system_prompt: say\n"
        '    user_template: "{old}\\n{new}"\n'
    )
    (folder / "checks.yaml").write_text(text, encoding="utf-8")


def test_checks_listed_from_inherited_checks_yaml(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    seeded = {item.id: item.label for item in bridge.checks_for(project)}
    assert seeded["project_impact"] == "Project impact"
    assert "sustainability_impact" in seeded
    _write_checks(project_dir.parent / ".iterthink" / "settings", "workspace_only", "Workspace")
    workspace = bridge.checks_for(project)
    assert [item.id for item in workspace] == ["workspace_only"]
    _write_checks(project_dir / ".iterthink" / "settings", "project_only", "Project")
    project_layer = bridge.checks_for(project)
    assert [item.id for item in project_layer] == ["project_only"]


def test_check_respects_egress_none(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    bridge.set_egress(project, "none", "user:ada")
    cloud = _Model('{"symbol":"−−","finding":"cloud"}', tier="cloud")
    bridge.use_checks_model(cloud)
    blocked = bridge.run_check(project, "Pflichtenheft.md", "project_impact", "user:ada")
    assert cloud.calls == []
    assert blocked.symbols == ()
    local = _Model('{"symbol":"~","finding":"local doors"}', tier="local")
    bridge.use_checks_model(local)
    allowed = bridge.run_check(project, "Pflichtenheft.md", "project_impact", "user:ada")
    assert local.calls
    assert allowed.symbols[0].symbol == "~"
    assert "local doors" in allowed.symbols[0].finding


def test_cached_result_reused_for_same_version(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    model = _Model('{"symbol":"~","finding":"doors stay"}')
    bridge.use_checks_model(model)
    first = bridge.run_check(project, "Pflichtenheft.md", "project_impact", "user:ada")
    seen = len(model.calls)
    assert seen > 0
    assert first.symbols[0].symbol == "~"
    logged = [event for event in read_all(project_dir) if event.type == "check"]
    assert logged
    assert logged[-1].payload["check"] == "project_impact"
    assert logged[-1].payload["prompt_version"]
    assert logged[-1].payload["model"] == "local"
    assert "EI30" not in str(logged[-1].payload)
    second = bridge.run_check(project, "Pflichtenheft.md", "project_impact", "user:ada")
    assert len(model.calls) == seen
    assert second.cached is True
    assert second.symbols == first.symbols
    again = [event for event in read_all(project_dir) if event.type == "check"]
    assert len(again) == len(logged)
    bridge.save(project, "Pflichtenheft.md", "# Pflichtenheft\n\nNeu.\n", "user:ada", "edit")
    third = bridge.run_check(project, "Pflichtenheft.md", "project_impact", "user:ada")
    assert len(model.calls) > seen
    assert third.cached is False
