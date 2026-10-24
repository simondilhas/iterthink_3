"""Workspaces: first-level candidates, ignore, and the default folder."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from iterthink import config
from iterthink.services.bridge import Forbidden, Invalid, NotFound
from iterthink.services.bridge_real import RealBridge


@pytest.fixture
def documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "Documents" / "iterthink"
    monkeypatch.setattr(config, "DOCUMENTS", root)
    return root


def _bridge(tmp_path: Path) -> RealBridge:
    return RealBridge(state_dir=tmp_path / "state", machine="m-test")


def test_workspace_lists_first_level_folders_as_project_candidates(
    tmp_path: Path, documents: Path, project_dir: Path, second_project_dir: Path
) -> None:
    root = project_dir.parent
    (root / "Neu").mkdir()
    (root / ".secret").mkdir()
    (project_dir / "EG").mkdir()
    bridge = _bridge(tmp_path)
    made = bridge.make_project(project_dir)
    bridge.propose(made.id, {"Pflichtenheft.md": "Neu\n"}, "user:ada", "retitle")
    opened = {item.name for item in bridge.open_folder(root)}
    assert opened == {project_dir.name, second_project_dir.name, "Neu"}
    items = {item.name: item for item in bridge.workspace_view(root)}
    assert set(items) == opened
    assert items[project_dir.name].project_id == made.id
    assert items[project_dir.name].proposals == 1
    assert items[second_project_dir.name].project_id is None
    assert items["Neu"].prompt is False
    assert root.resolve() in bridge.workspaces()
    own = bridge.open_folder(project_dir)
    assert [item.project_id for item in own] == [made.id]
    assert project_dir.resolve() not in bridge.workspaces()
    assert not documents.exists()


def test_untracked_files_in_workspace_are_flagged_not_moved(
    tmp_path: Path, documents: Path
) -> None:
    root = tmp_path / "jobs"
    (root / "Schulhaus").mkdir(parents=True)
    (root / "Schulhaus" / "inside.txt").write_text("in", encoding="utf-8")
    note = root / "notes.txt"
    note.write_text("hello", encoding="utf-8")
    (root / ".hidden.txt").write_text("no", encoding="utf-8")
    bridge = _bridge(tmp_path)
    view = bridge.workspace_view(root)
    loose = [item for item in view if item.untracked]
    assert [item.name for item in loose] == ["notes.txt"]
    assert [item.name for item in view if not item.untracked] == ["Schulhaus"]
    with pytest.raises(NotFound):
        bridge.make_project(note)
    assert note.read_text(encoding="utf-8") == "hello"
    assert note.parent.resolve() == root.resolve()
    assert (root / "Schulhaus" / "inside.txt").is_file()
    empty = tmp_path / "empty"
    empty.mkdir()
    assert bridge.workspace_view(empty) == []
    assert empty.resolve() not in bridge.workspaces()


def test_ignore_is_remembered_per_workspace(tmp_path: Path, documents: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    (first / "Skip").mkdir(parents=True)
    (first / "Keep").mkdir()
    (second / "Skip").mkdir(parents=True)
    (second / "Other").mkdir()
    bridge = _bridge(tmp_path)
    bridge.workspace_view(first)
    bridge.workspace_view(second)
    bridge.workspace_ignore(first, "Skip")
    assert (first / "Skip").is_dir()
    stored = first / ".iterthink" / "settings" / "ignore.yaml"
    assert "Skip" in stored.read_text(encoding="utf-8")
    assert not (second / ".iterthink").exists()
    again = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    left = {item.name for item in again.workspace_view(first)}
    right = {item.name for item in again.workspace_view(second)}
    assert left == {"Keep"}
    assert "Skip" in right
    with pytest.raises(Forbidden):
        again.workspace_ignore(tmp_path / "nope", "Skip")
    with pytest.raises(Invalid):
        again.workspace_ignore(first, "Skip/nested")


def test_default_workspace_is_created_and_always_known(tmp_path: Path, documents: Path) -> None:
    other = tmp_path / "other"
    (other / "Kid").mkdir(parents=True)
    bridge = _bridge(tmp_path)
    assert not documents.exists()
    bridge.open_folder(other)
    found = bridge.default_workspace()
    assert found == documents.resolve()
    assert documents.is_dir()
    bridge.default_workspace()
    known = bridge.workspaces()
    assert known[0] == found
    assert known.count(found) == 1
    assert other.resolve() in known[1:]


def test_relative_make_project_creates_folder_in_default_workspace(
    tmp_path: Path, documents: Path
) -> None:
    bridge = _bridge(tmp_path)
    info = bridge.make_project(Path("Schulhaus"))
    assert Path(info.path) == (documents / "Schulhaus").resolve()
    assert info.name == "Schulhaus"
    assert (documents / "Schulhaus" / ".iterthink").is_dir()
    assert bridge.workspaces()[0] == documents.resolve()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "a.txt").write_text("x", encoding="utf-8")
    other = bridge.make_project(elsewhere)
    assert Path(other.path) == elsewhere.resolve()
    assert (elsewhere / "a.txt").read_text(encoding="utf-8") == "x"
    again = bridge.make_project(elsewhere)
    assert again.id == other.id
    copy = tmp_path / "Schulhaus-copy"
    shutil.copytree(documents / "Schulhaus", copy)
    copied = bridge.make_project(copy)
    assert copied.id == info.id
    assert Path(copied.path) == (documents / "Schulhaus").resolve()
    (elsewhere.parent / ".iterthink").mkdir()
    panel = bridge.explorer_panel(other.id)
    assert panel.root == ""
    assert other.id in {item.project_id for item in panel.projects}


def test_new_project_name_is_sanitised_and_never_reuses_a_folder(
    tmp_path: Path, documents: Path
) -> None:
    bridge = _bridge(tmp_path)
    cleaned = bridge.make_project(Path('A/B:C*?"<>|\t'))
    assert Path(cleaned.path).name == "ABC"
    assert (documents / "ABC").is_dir()
    first = bridge.make_project(Path("Halle"))
    marker = Path(first.path) / "keep.txt"
    marker.write_text("stay", encoding="utf-8")
    second = bridge.make_project(Path("Halle"))
    assert Path(second.path).name == "Halle 2"
    assert marker.read_text(encoding="utf-8") == "stay"
    assert Path(first.path).is_dir()
    third = bridge.make_project(Path("  Halle  "))
    assert Path(third.path).name == "Halle 3"
    with pytest.raises(Invalid):
        bridge.make_project(Path("***"))
    with pytest.raises(Invalid):
        bridge.make_project(Path(".."))
