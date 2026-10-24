"""Markdown documents: create, margin actions, proposals, egress, and the log."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from iterthink import config
from iterthink.compare.margin import split_paragraphs
from iterthink.privacy_shield_settings import load_categories
from iterthink.services.bridge import Invalid
from iterthink.services.bridge_real import RealBridge
from iterthink.services.documents import create, margin_actions, run_margin_action
from iterthink.services.event_log import read_all

_SEED = Path(__file__).resolve().parents[3] / "iterthink" / "defaults" / "prompts.yaml"
_DOC = "Pflichtenheft.md"


class _Router:
    def __init__(self, text: str = "SUGGESTED", tier: str = "local", model: str = "fake") -> None:
        self.text = text
        self.tier = tier
        self.model = model
        self.calls: list[str] = []

    def stream(self, system: str, user: str, tier: str) -> Iterator[str]:
        self.calls.append(tier)
        assert system
        assert user
        yield self.text


@pytest.fixture(autouse=True)
def _shield_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "STORE_DIR", tmp_path / "shield")
    load_categories(reload=True)


def _bridge(tmp_path: Path) -> RealBridge:
    return RealBridge(state_dir=tmp_path / "state", machine="m-test")


def _project(tmp_path: Path, project_dir: Path) -> tuple[RealBridge, str]:
    bridge = _bridge(tmp_path)
    return bridge, bridge.make_project(project_dir).id


def _run(
    project_dir: Path,
    bridge: RealBridge,
    project: str,
    router: _Router,
    *,
    action_id: str,
    paragraph: int = 1,
    selection: str | None = None,
    instruction: str | None = None,
    draft: str | None = None,
) -> list[str]:
    return list(
        run_margin_action(
            project_dir,
            path=_DOC,
            paragraph=paragraph,
            selection=selection,
            action_id=action_id,
            instruction=instruction,
            router=router,
            draft=draft,
            bridge=bridge,
            actor="user:ada",
            project=project,
        )
    )


def test_create_writes_md_where_user_says_and_never_overwrites(
    tmp_path: Path, project_dir: Path
) -> None:
    bridge, project = _project(tmp_path, project_dir)
    path = create(bridge, project, "Pläne", "Brandschutz", "Brandschutz", "user:ada")
    assert path == "Pläne/Brandschutz.md"
    target = project_dir / "Pläne" / "Brandschutz.md"
    assert target.read_text(encoding="utf-8").startswith("# Brandschutz")
    with pytest.raises(Invalid):
        create(bridge, project, "Pläne", "Brandschutz", "Other", "user:ada")
    assert target.read_text(encoding="utf-8").startswith("# Brandschutz")


def test_margin_actions_come_from_prompts_yaml(project_dir: Path) -> None:
    loaded = yaml.safe_load(_SEED.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    raw = loaded["margin_actions"]
    assert isinstance(raw, list)
    actions = margin_actions(project_dir)
    assert [item.id for item in actions] == [entry["id"] for entry in raw]
    assert {item.topic for item in actions} <= {"discuss", "change", "evaluate"}
    assert any(item.topic == "discuss" for item in actions)
    assert any(item.topic == "change" for item in actions)


def test_mod_enter_edit_creates_proposal_not_edit(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _project(tmp_path, project_dir)
    target = project_dir / _DOC
    before = target.read_text(encoding="utf-8")
    router = _Router()
    chunks = _run(project_dir, bridge, project, router, action_id="grammar", instruction="fix it")
    assert "".join(chunks) == "SUGGESTED"
    assert target.read_text(encoding="utf-8") == before
    proposals = bridge.proposals(project)
    assert len(proposals) == 1
    assert proposals[0].reason == "fix it"
    bridge.accept(project, proposals[0].id, "user:ada")
    parts = split_paragraphs(target.read_text(encoding="utf-8"))
    assert parts[1] == "SUGGESTED"
    assert "EI30" not in parts[1]


def test_unsaved_edits_saved_before_proposal(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _project(tmp_path, project_dir)
    target = project_dir / _DOC
    original = target.read_text(encoding="utf-8")
    draft = original.replace("EI30", "EI90")
    before = len(bridge.history(project, _DOC))
    _run(
        project_dir,
        bridge,
        project,
        _Router(),
        action_id="grammar",
        instruction="tighten",
        draft=draft,
        selection="EI90",
    )
    saved = target.read_text(encoding="utf-8")
    assert "EI90" in saved
    assert "SUGGESTED" not in saved
    assert len(bridge.history(project, _DOC)) == before + 1
    proposals = bridge.proposals(project)
    assert len(proposals) == 1
    diff = bridge.proposal_diff(project, proposals[0].id)
    assert any(block.after == "SUGGESTED" or "SUGGESTED" in block.after for block in diff[0].blocks)


def test_egress_none_uses_local_model_only(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _project(tmp_path, project_dir)
    bridge.set_egress(project, "none", "user:ada")
    router = _Router(text="A short summary.", tier="cloud")
    chunks = _run(project_dir, bridge, project, router, action_id="create_summary")
    assert "".join(chunks) == "A short summary."
    assert router.calls == ["local"]
    assert (project_dir / _DOC).read_text(encoding="utf-8").count("EI30") == 1
    assert bridge.proposals(project) == []


def test_margin_action_is_logged(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _project(tmp_path, project_dir)
    _run(project_dir, bridge, project, _Router(text="A short summary."), action_id="create_summary")
    events = [event for event in read_all(project_dir) if event.type == "margin"]
    assert len(events) == 1
    event = events[0]
    assert event.actor == "user:ada"
    payload = event.payload
    assert payload["action"] == "create_summary"
    assert payload["paragraph"] == 1
    assert payload["model"] == "fake"
    version = payload["prompt_version"]
    assert isinstance(version, str)
    assert version
    assert str(payload["text"]).startswith("blob:")
    assert str(payload["answer"]).startswith("blob:")
    assert "EI30" not in str(payload)
    assert "Türen" not in str(payload)
