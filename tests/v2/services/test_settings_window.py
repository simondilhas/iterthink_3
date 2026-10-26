"""Rows per section, where each value comes from, Ollama status and settings files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from iterthink.ai.local_model import LocalModel
from iterthink.services.bridge import Invalid
from iterthink.services.bridge_real import RealBridge

SECTIONS = [
    "models",
    "privacy",
    "appearance",
    "paths",
    "dictation",
    "prompts",
    "index",
    "storage",
    "shortcuts",
]


class _Client:
    def __init__(self, names: list[str] | None = None, fail: bool = False) -> None:
        self.names = names or []
        self.fail = fail
        self.chats: list[str] = []

    def list(self) -> dict[str, Any]:
        if self.fail:
            raise ConnectionError("refused")
        return {"models": [{"model": name} for name in self.names]}

    def chat(self, **kwargs: Any) -> dict[str, Any]:
        self.chats.append(str(kwargs["model"]))
        return {"message": {"content": ""}}


def _bridge(tmp_path: Path) -> RealBridge:
    return RealBridge(state_dir=tmp_path / "state", machine="m-test")


def _rows(bridge: RealBridge, project: str | None) -> dict[str, Any]:
    return {row.key: row for section in bridge.settings_sections(project) for row in section.rows}


def test_sections_come_in_order(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    assert [section.name for section in bridge.settings_sections(project)] == SECTIONS


def test_rows_carry_their_source(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    bridge.set_window_setting(project, "dictation.language", "de", "project", "user:ada")
    bridge.set_window_setting(project, "appearance", "dark", "machine", "user:ada")
    rows = _rows(bridge, project)
    assert (rows["dictation.language"].value, rows["dictation.language"].source) == (
        "de",
        "project",
    )
    assert rows["dictation.model"].source == "default"
    assert (rows["appearance"].value, rows["appearance"].source) == ("dark", "machine")
    assert rows["egress"].value == "shielded"
    assert bridge.appearance() == "dark"


def test_use_default_clears_an_override(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    bridge.set_window_setting(project, "dictation.model", "tiny", "workspace", "user:ada")
    row = bridge.clear_window_setting(project, "dictation.model", "workspace", "user:ada")
    assert (row.value, row.source) == ("small", "default")


def test_start_screen_writes_inherited_values_to_the_default_workspace(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    workspace = tmp_path / "Arbeit"
    workspace.mkdir()
    bridge.set_window_setting(None, "documents_root", str(workspace), "machine", "user:ada")
    row = bridge.set_window_setting(None, "shortcuts.line", "Mod+L", "workspace", "user:ada")
    assert (row.value, row.source) == ("Mod+L", "workspace")
    assert "Mod+L" in (workspace / ".iterthink" / "settings" / "values.yaml").read_text()
    assert bridge.shortcut_keys(None)["line"] == "Mod+L"
    names = [section.name for section in bridge.settings_sections(None)]
    assert "index" not in names
    assert "egress" not in _rows(bridge, None)


def test_ollama_status_with_a_fake_client(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge._ollama_client = _Client(["qwen2.5:3b", "mistral:latest"])
    status = bridge.ollama_status()
    assert status.running
    assert status.models == ("mistral:latest", "qwen2.5:3b")
    assert status.missing == ("llama3:8B",)
    bridge._ollama_client = _Client(fail=True)
    assert not bridge.ollama_status().running


def test_changing_the_line_model_reconnects(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    client = _Client(["llama3:8b"])
    bridge._ollama_client = client
    bridge.use_local_model()
    bridge.set_window_setting(None, "line_model", "llama3:8b", "machine", "user:ada")
    router = bridge._intent_router
    assert isinstance(router, LocalModel)
    assert router.model == "llama3:8b"


def test_settings_file_refuses_invalid_yaml(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    seed = Path("iterthink/defaults/prompts.yaml").read_text(encoding="utf-8")
    assert bridge.settings_file(project, "prompts.yaml", "project") == seed
    with pytest.raises(Invalid, match="YAML"):
        bridge.save_settings_file(project, "prompts.yaml", "project", "a: [unclosed")
    with pytest.raises(Invalid, match="settings file"):
        bridge.save_settings_file(project, "../evil.yaml", "project", "a: 1")
    bridge.save_settings_file(project, "rules.yaml", "project", "# mine\nrules: []\n")
    saved = project_dir / ".iterthink" / "settings" / "rules.yaml"
    assert saved.read_text(encoding="utf-8") == "# mine\nrules: []\n"
    assert bridge.settings_file(project, "rules.yaml", "project") == "# mine\nrules: []\n"


def test_index_status_and_rebuild(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    status = bridge.index_rebuild(project)
    assert int(str(status["events"])) > 0
    assert bridge.index_status(project)["events"] == status["events"]
