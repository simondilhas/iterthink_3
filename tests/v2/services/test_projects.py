"""Project identity on the real bridge."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from iterthink.services.bridge import Forbidden
from iterthink.services.bridge_real import RealBridge

MAX_BYTES = 200 * 1024 * 1024


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    return tmp_path / "state"


@pytest.fixture
def bridge(state_dir: Path) -> RealBridge:
    return RealBridge(state_dir=state_dir, machine="m-test")


def test_machine_id_created_once(state_dir: Path) -> None:
    first = RealBridge(state_dir=state_dir)
    second = RealBridge(state_dir=state_dir)
    assert first.machine == second.machine
    assert len(first.machine) == 10
    assert first.machine.startswith("m-")
    text = (state_dir / "machine.yaml").read_text(encoding="utf-8")
    assert first.machine in text
    RealBridge(state_dir=state_dir)
    assert (state_dir / "machine.yaml").read_text(encoding="utf-8") == text


def test_project_id_survives_move(bridge: RealBridge, project_dir: Path, tmp_path: Path) -> None:
    info = bridge.make_project(project_dir)
    bridge.save(info.id, "Pflichtenheft.md", "eins\n", "user:simon")
    before = [item.id for item in bridge.history(info.id)]
    moved = tmp_path / "moved"
    shutil.move(project_dir, moved)
    again = RealBridge(state_dir=bridge.state_dir, machine="m-test")
    opened = again.make_project(moved)
    assert opened.id == info.id
    assert [item.id for item in again.history(info.id)] == before


def test_copy_is_detected_when_both_paths_exist(
    bridge: RealBridge, project_dir: Path, tmp_path: Path
) -> None:
    info = bridge.make_project(project_dir)
    copied = tmp_path / "copy"
    shutil.copytree(project_dir, copied)
    again = RealBridge(state_dir=bridge.state_dir, machine="m-test")
    again.open_folder(copied)
    assert [item.path for item in again.projects()] == [str(project_dir.resolve())]
    assert any(entry.type == "copy_suspected" for entry in again.log(info.id))


def test_hidden_and_large_files_are_not_tracked(bridge: RealBridge, project_dir: Path) -> None:
    (project_dir / ".secret").write_text("hidden\n", encoding="utf-8")
    nested = project_dir / "Pläne" / ".draft.md"
    nested.write_text("hidden\n", encoding="utf-8")
    big = project_dir / "big.bin"
    with big.open("wb") as handle:
        handle.truncate(MAX_BYTES + 1)
    info = bridge.make_project(project_dir)
    paths = {entry.path for entry in bridge.files(info.id)}
    assert ".secret" not in paths
    assert "Pläne/.draft.md" not in paths
    assert "big.bin" not in paths
    assert all(".secret" not in item.paths for item in bridge.history(info.id))
    assert all("big.bin" not in item.paths for item in bridge.history(info.id))


@pytest.mark.parametrize("which", ["home", "parent", "root"])
def test_home_folder_and_above_are_refused(
    bridge: RealBridge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, which: str
) -> None:
    home = tmp_path / "home" / "simon"
    home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    folder = {"home": home, "parent": home.parent, "root": Path(home.anchor)}[which]
    with pytest.raises(Forbidden, match="too broad"):
        bridge.make_project(folder)
    assert not (home / ".iterthink").exists()
    assert not (home.parent / ".iterthink").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_unwritable_folder_says_so(bridge: RealBridge, tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    try:
        with pytest.raises(Forbidden, match=f"cannot write to {locked}"):
            bridge.make_project(locked)
    finally:
        locked.chmod(0o755)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file attribute")
def test_windows_hidden_attribute(bridge: RealBridge, project_dir: Path) -> None:
    import ctypes

    bridge.make_project(project_dir)
    attrs = ctypes.windll.kernel32.GetFileAttributesW(  # type: ignore[attr-defined]
        str(project_dir / ".iterthink")
    )
    assert attrs != -1
    assert attrs & 0x02
