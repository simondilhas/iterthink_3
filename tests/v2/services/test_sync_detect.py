"""A cloud-sync folder warns, and a conflict copy stays its own candidate."""

from __future__ import annotations

from pathlib import Path

from iterthink.services.sync_detect import cloud_warning, conflict_copies


def test_cloud_sync_folder_warns_and_conflict_copy_is_candidate(tmp_path: Path) -> None:
    folder = tmp_path / "OneDrive" / "P-101"
    folder.mkdir(parents=True)
    warning = cloud_warning(folder)
    assert "synced" in warning
    assert "conflict" in warning
    (folder / "note (conflicted copy).md").write_text("other\n", encoding="utf-8")
    (folder / "note-PC-ada.md").write_text("pc\n", encoding="utf-8")
    (folder / "note.md").write_text("ours\n", encoding="utf-8")
    copies = conflict_copies(folder)
    assert "note (conflicted copy).md" in copies
    assert "note-PC-ada.md" in copies
    assert "note.md" not in copies
    partial = Path("iterthink/web/templates/project/_sync_warning.html")
    assert "sync_warning" in partial.read_text(encoding="utf-8")
