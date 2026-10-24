"""Settings inherit from defaults, the workspace, then the project."""

from __future__ import annotations

from pathlib import Path

import pytest

from iterthink.services import settings as settings_mod
from iterthink.services.bridge_real import RealBridge
from iterthink.services.event_log import read_all
from iterthink.services.projects import write_yaml
from iterthink.services.settings import get, load_yaml, storage, upgrade


def _bridge(tmp_path: Path, project_dir: Path) -> tuple[RealBridge, str]:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    return bridge, bridge.make_project(project_dir).id


def test_inheritance_default_workspace_project(project_dir: Path) -> None:
    assert get(project_dir, "model.local").value == "llama3:8B"
    assert get(project_dir, "model.local").source == "default"
    workspace = project_dir.parent / ".iterthink" / "settings"
    write_yaml(workspace / "values.yaml", {"model.local": "from-workspace"})
    assert get(project_dir, "model.local").value == "from-workspace"
    assert get(project_dir, "model.local").source == "workspace"
    write_yaml(
        project_dir / ".iterthink" / "settings" / "values.yaml", {"model.local": "from-project"}
    )
    assert get(project_dir, "model.local").value == "from-project"
    assert get(project_dir, "model.local").source == "project"


def test_source_shown_for_each_value(project_dir: Path) -> None:
    shown = {item.key: item.source for item in settings_mod.all_settings(project_dir)}
    assert shown["dictation.language"] == "default"
    assert shown["dictation.model"] == "default"
    assert shown["runner.max_parallel_local"] == "default"
    assert shown["runner.max_parallel_cloud"] == "default"
    assert shown["storage.versions"] == "project"


def test_load_yaml_merges_mappings_replaces_lists(project_dir: Path) -> None:
    workspace = project_dir.parent / ".iterthink" / "settings"
    write_yaml(workspace / "sample.yaml", {"a": {"x": 1, "y": 1}, "tags": [1]})
    write_yaml(
        project_dir / ".iterthink" / "settings" / "sample.yaml", {"a": {"y": 2}, "tags": [2, 3]}
    )
    merged = load_yaml(project_dir, "sample.yaml")
    assert merged["a"] == {"x": 1, "y": 2}
    assert merged["tags"] == [2, 3]


def test_upgrade_merges_new_keys_and_asks_for_changed(
    tmp_path: Path, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "demo.yaml").write_text("a: 1\nb: 1\nc: 0\n", encoding="utf-8")
    monkeypatch.setattr(settings_mod, "SEEDS_DIR", seeds)
    folder = project_dir / ".iterthink" / "settings"
    write_yaml(folder / "_base" / "demo.yaml", {"a": 1, "b": 1})
    write_yaml(folder / "demo.yaml", {"a": 1, "b": 9})
    (seeds / "demo.yaml").write_text("a: 2\nb: 3\nc: 4\n", encoding="utf-8")
    questions = upgrade(project_dir)
    saved = settings_mod._read_any(folder / "demo.yaml")
    assert saved["a"] == 2
    assert saved["b"] == 9
    assert saved["c"] == 4
    assert questions == [{"file": "demo.yaml", "key": "b", "mine": 9, "new": 3}]


def test_changes_logged(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    bridge.set_setting(project, "dictation.language", "de", "project", "user:ada")
    events = [
        event for event in read_all(project_dir) if event.payload.get("key") == "dictation.language"
    ]
    assert events[-1].payload["old"] == "auto"
    assert events[-1].payload["new"] == "de"
    assert events[-1].actor == "user:ada"


def test_secrets_never_written_to_yaml(
    tmp_path: Path, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored: list[tuple[str, str, str]] = []

    def remember(service: str, key: str, value: str) -> None:
        stored.append((service, key, value))

    monkeypatch.setattr(settings_mod.keyring, "set_password", remember)
    bridge, project = _bridge(tmp_path, project_dir)
    bridge.set_setting(project, "company.api_key", "sk-secret", "project", "user:ada")
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (project_dir / ".iterthink").rglob("*")
        if path.is_file()
    )
    assert "sk-secret" not in text
    assert stored == [("iterthink", "company.api_key", "sk-secret")]


def test_storage_growth_reported(project_dir: Path) -> None:
    before = storage(project_dir)
    log = project_dir / ".iterthink" / "log"
    log.mkdir(parents=True, exist_ok=True)
    (log / "extra.jsonl").write_text("x" * 40, encoding="utf-8")
    after = storage(project_dir)
    assert after["log"] > before["log"]
    assert after["log_delta"] == 40
    assert after["versions"] == before["versions"]
