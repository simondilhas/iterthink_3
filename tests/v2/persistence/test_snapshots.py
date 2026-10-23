"""Acceptance tests for content-addressed snapshots (slice A3)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

from iterthink.persistence.snapshots import SnapshotError, Snapshots


def _open(project: Path) -> Snapshots:
    store = Snapshots(project)
    store.init()
    return store


def test_init_creates_versions_dirs_only(
    project_dir: Path, source_snapshot: Callable[[Path], dict[str, str]]
) -> None:
    before = source_snapshot(project_dir)
    store = Snapshots(project_dir)
    store.init()
    root = project_dir / ".iterthink" / "versions"
    assert (root / "objects").is_dir()
    assert (root / "snapshots").is_dir()
    assert not (project_dir / ".jj").exists()
    assert not (project_dir / ".git").exists()
    assert not (project_dir / ".gitignore").exists()
    assert not any(path.name == ".gitignore" for path in project_dir.rglob("*"))
    assert source_snapshot(project_dir) == before


def test_init_is_idempotent(tmp_path: Path) -> None:
    store = Snapshots(tmp_path)
    store.init()
    store.init()
    assert (tmp_path / ".iterthink" / "versions" / "objects").is_dir()
    assert (tmp_path / ".iterthink" / "versions" / "snapshots").is_dir()


def test_snapshot_returns_id_and_paths(tmp_path: Path) -> None:
    store = _open(tmp_path)
    version = store.snapshot({"notes/a.md": b"hi"}, "start", "user:simon")
    assert version is not None
    assert len(version.id) == 64
    assert version.paths == ("notes/a.md",)
    assert version.author == "user:simon"
    assert version.description == "start"
    assert version.timestamp.endswith("Z")
    assert store.head().id == version.id


def test_snapshot_without_changes_returns_none(tmp_path: Path) -> None:
    store = _open(tmp_path)
    first = store.snapshot({"a.txt": b"hi"}, "first", "user:simon")
    assert first is not None
    assert store.snapshot({"a.txt": b"hi"}, "again", "user:simon") is None
    assert store.head().id == first.id


def test_object_is_content_addressed(tmp_path: Path) -> None:
    store = _open(tmp_path)
    store.snapshot({"a.txt": b"same", "b.txt": b"same"}, "dup", "user:simon")
    objects = tmp_path / ".iterthink" / "versions" / "objects"
    stored = [path for path in objects.iterdir() if not path.name.startswith(".")]
    digest = hashlib.sha256(b"same").hexdigest()
    assert [path.name for path in stored] == [digest]
    assert stored[0].read_bytes() == b"same"


def test_object_write_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _open(tmp_path)
    first = store.snapshot({"a.txt": b"one"}, "first", "user:simon")
    assert first is not None
    real_replace = Path.replace

    def crash(self: Path, target: Path) -> Path:
        if self.parent.name == "objects":
            raise OSError("crash")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", crash)
    with pytest.raises(OSError, match="crash"):
        store.snapshot({"a.txt": b"two"}, "second", "user:simon")
    digest = hashlib.sha256(b"two").hexdigest()
    assert not (tmp_path / ".iterthink" / "versions" / "objects" / digest).exists()
    assert store.file_at(first.id, "a.txt") == b"one"
    assert store.head().id == first.id


def test_large_file_is_stored(tmp_path: Path) -> None:
    store = _open(tmp_path)
    blob = b"x" * (5 * 1024 * 1024)
    version = store.snapshot({"plan.bin": blob}, "big", "user:simon")
    assert version is not None
    assert store.file_at(version.id, "plan.bin") == blob


def test_history_newest_first(tmp_path: Path) -> None:
    store = _open(tmp_path)
    first = store.snapshot({"a.txt": b"1"}, "first", "user:simon")
    second = store.snapshot({"a.txt": b"2"}, "second", "user:simon")
    assert first is not None
    assert second is not None
    assert [item.id for item in store.history()] == [second.id, first.id]


def test_history_filtered_by_path(tmp_path: Path) -> None:
    store = _open(tmp_path)
    first = store.snapshot({"a.txt": b"1"}, "first", "user:simon")
    second = store.snapshot({"b.txt": b"2"}, "second", "user:simon")
    assert first is not None
    assert second is not None
    assert [item.id for item in store.history("a.txt")] == [first.id]
    assert [item.id for item in store.history("b.txt")] == [second.id]


def test_file_at_returns_old_bytes_and_none_when_absent(tmp_path: Path) -> None:
    store = _open(tmp_path)
    first = store.snapshot({"a.txt": b"one"}, "first", "user:simon")
    second = store.snapshot({"a.txt": b"two"}, "second", "user:simon")
    assert first is not None
    assert second is not None
    assert store.file_at(first.id, "a.txt") == b"one"
    assert store.file_at(second.id, "a.txt") == b"two"
    assert store.file_at(first.id, "missing.txt") is None


def test_restore_creates_new_version_and_keeps_old(tmp_path: Path) -> None:
    store = _open(tmp_path)
    first = store.snapshot({"a.txt": b"one", "b.txt": b"b1"}, "first", "user:simon")
    second = store.snapshot({"a.txt": b"two", "b.txt": b"b2"}, "second", "user:simon")
    assert first is not None
    assert second is not None
    restored = store.restore(first.id, ["a.txt"], "bring back", "user:simon")
    assert store.file_at(restored.id, "a.txt") == b"one"
    assert store.file_at(restored.id, "b.txt") == b"b2"
    assert store.file_at(first.id, "a.txt") == b"one"
    assert store.file_at(second.id, "a.txt") == b"two"
    assert store.head().id == restored.id
    assert store.history()[0].id == restored.id


def test_draft_leaves_source_files_untouched(
    project_dir: Path, source_snapshot: Callable[[Path], dict[str, str]]
) -> None:
    before = source_snapshot(project_dir)
    store = _open(project_dir)
    base = store.snapshot({"Pflichtenheft.md": b"old"}, "base", "user:simon")
    assert base is not None
    drafted = store.draft(base.id, {"Pflichtenheft.md": b"new"}, "proposal", "agent:ada")
    assert store.read_draft(drafted.id) == {"Pflichtenheft.md": b"new"}
    assert store.file_at(base.id, "Pflichtenheft.md") == b"old"
    assert store.head().id == base.id
    assert (project_dir / "Pflichtenheft.md").read_bytes() != b"new"
    assert source_snapshot(project_dir) == before


def test_paths_with_spaces_and_umlauts(tmp_path: Path) -> None:
    store = _open(tmp_path)
    name = "Pläne/Notiz EG.md"
    version = store.snapshot({name: "Tür".encode()}, "plan", "user:simon")
    assert version is not None
    assert version.paths == (name,)
    assert store.file_at(version.id, name) == "Tür".encode()


def test_path_escape_raises(tmp_path: Path) -> None:
    store = _open(tmp_path)
    saved = store.snapshot({"a.txt": b"ok"}, "ok", "user:simon")
    assert saved is not None
    for bad in ("../x", "/etc/passwd", ".iterthink/log/a", "foo/../../x", "a/../b"):
        with pytest.raises(SnapshotError):
            store.snapshot({bad: b"x"}, "no", "user:simon")
        with pytest.raises(SnapshotError):
            store.history(bad)
        with pytest.raises(SnapshotError):
            store.file_at(saved.id, bad)
