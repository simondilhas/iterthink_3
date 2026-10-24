"""Impact advice lists files and never decides."""

from __future__ import annotations

from pathlib import Path

from iterthink.services.bridge_real import RealBridge


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


def test_impact_runs_on_proposal_and_lists_affected_files(
    tmp_path: Path, project_dir: Path
) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    info = bridge.propose(
        project,
        {"Pflichtenheft.md": "# Pflichtenheft\n\nDie Türen sind EI60.\n"},
        "user:ada",
        "retitle",
    )
    model = _Model(
        '{"suggestion":"check the door list","affected":["Türliste.csv"],"confidence":"0.80"}'
    )
    bridge.use_impact_model(model)
    advice = bridge.impact_advice(project, info.id, "user:ada")
    assert "Türliste.csv" in advice.affected
    assert advice.suggestion
    assert model.calls == ["local"]


def test_impact_never_decides(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    info = bridge.propose(
        project, {"Pflichtenheft.md": "# Pflichtenheft\n\nNeu.\n"}, "user:ada", "retitle"
    )
    bridge.use_impact_model(_Model('{"suggestion":"leave it","affected":[],"confidence":"0.40"}'))
    bridge.impact_advice(project, info.id, "user:ada")
    found = next(item for item in bridge.proposals(project, status=None) if item.id == info.id)
    assert found.status == "open"
    assert found.decided_by is None


def test_impact_respects_egress_none(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    info = bridge.propose(
        project, {"Pflichtenheft.md": "# Pflichtenheft\n\nNeu.\n"}, "user:ada", "retitle"
    )
    bridge.set_egress(project, "none", "user:ada")
    cloud = _Model(
        '{"suggestion":"cloud","affected":["Türliste.csv"],"confidence":"0.90"}', tier="cloud"
    )
    bridge.use_impact_model(cloud)
    blocked = bridge.impact_advice(project, info.id, "user:ada")
    assert cloud.calls == []
    assert blocked.affected == ()
    local = _Model(
        '{"suggestion":"local","affected":["Türliste.csv"],"confidence":"0.70"}', tier="local"
    )
    bridge.use_impact_model(local)
    allowed = bridge.impact_advice(project, info.id, "user:ada")
    assert local.calls == ["local"]
    assert "Türliste.csv" in allowed.affected


def test_cached_result_reused(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    info = bridge.propose(
        project, {"Pflichtenheft.md": "# Pflichtenheft\n\nNeu.\n"}, "user:ada", "retitle"
    )
    model = _Model('{"suggestion":"once","affected":["Türliste.csv"],"confidence":"0.60"}')
    bridge.use_impact_model(model)
    first = bridge.impact_advice(project, info.id, "user:ada")
    second = bridge.impact_advice(project, info.id, "user:ada")
    assert model.calls == ["local"]
    assert second.cached is True
    assert second.affected == first.affected
