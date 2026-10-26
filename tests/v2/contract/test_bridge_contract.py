"""Behaviour every Bridge implementation must have. Human-owned: agents make
implementations pass these; they do not change them."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from iterthink.services.bridge import (
    Bridge,
    Conflict,
    Forbidden,
    Invalid,
    NotFound,
    kind_of,
)

from ..conftest import snapshot_sources
from .conftest import Ctx

MD = "Pflichtenheft.md"
CSV = "Türliste.csv"
VCS_WORDS = re.compile(r"\b(commit|branch|rebase|bookmark|repository|checkout|jj|git)\b", re.I)


# --- projects --------------------------------------------------------------


def test_open_folder_lists_subfolders_not_yet_projects(
    make_bridge: Callable[[], Bridge], project_dir: Path, second_project_dir: Path
) -> None:
    folders = make_bridge().open_folder(project_dir.parent)
    assert {f.name for f in folders} == {project_dir.name, second_project_dir.name}
    assert all(f.project_id is None for f in folders)


def test_make_project_keeps_sources_and_writes_only_own_folders(
    make_bridge: Callable[[], Bridge], project_dir: Path
) -> None:
    before = snapshot_sources(project_dir)
    entries_before = {p.name for p in project_dir.iterdir()}
    make_bridge().make_project(project_dir)
    assert snapshot_sources(project_dir) == before
    new = {p.name for p in project_dir.iterdir()} - entries_before
    assert new <= {".iterthink", ".jj"}
    assert not any(p.name in (".git", ".gitignore") for p in project_dir.rglob("*"))


def test_make_project_is_idempotent_and_id_lives_in_project(
    make_bridge: Callable[[], Bridge], project_dir: Path
) -> None:
    first = make_bridge().make_project(project_dir)
    again = make_bridge().make_project(project_dir)  # a fresh bridge reads the same id
    assert first.id == again.id
    assert first.id in (project_dir / ".iterthink/settings/project.yaml").read_text("utf-8")


def test_open_folder_finds_existing_project(
    make_bridge: Callable[[], Bridge], project_dir: Path
) -> None:
    pid = make_bridge().make_project(project_dir).id
    folders = make_bridge().open_folder(project_dir.parent)
    assert [f.project_id for f in folders if f.name == project_dir.name] == [pid]


def test_relative_path_makes_a_new_folder_in_the_default_workspace(
    make_bridge: Callable[[], Bridge], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from iterthink import config

    workspace = tmp_path / "Dokumente"
    monkeypatch.setattr(config, "DOCUMENTS", workspace)
    (workspace / "Neubau").mkdir(parents=True)
    info = make_bridge().make_project(Path("Neubau"))
    assert Path(info.path) == (workspace / "Neubau 2").resolve()
    assert (workspace / "Neubau 2" / ".iterthink/settings/project.yaml").is_file()
    assert list((workspace / "Neubau").iterdir()) == []


def test_default_egress_is_shielded_and_can_be_changed(ctx: Ctx) -> None:
    assert ctx.bridge.projects()[0].egress == "shielded"
    info = ctx.bridge.set_egress(ctx.project, "none", ctx.actor)
    assert info.egress == "none"
    assert "none" in (ctx.root / ".iterthink/settings/project.yaml").read_text("utf-8")


def test_unknown_project_raises_not_found(ctx: Ctx) -> None:
    with pytest.raises(NotFound):
        ctx.bridge.files("p-doesnotexist")


# --- files -----------------------------------------------------------------


def test_files_lists_sources_with_kinds_and_hides_own_data(ctx: Ctx) -> None:
    entries = {e.path: e for e in ctx.bridge.files(ctx.project)}
    assert {MD, CSV, "Pläne/Notiz Grundriss EG.md"} <= set(entries)
    assert entries[MD].kind == "markdown"
    assert entries[CSV].kind == "table"
    assert not any(p.startswith((".iterthink", ".jj")) for p in entries)


def test_read_returns_text(ctx: Ctx) -> None:
    content = ctx.bridge.read(ctx.project, MD)
    assert content.text is not None
    assert "EI30" in content.text
    assert content.kind == "markdown"


def test_read_binary_returns_no_text(ctx: Ctx) -> None:
    (ctx.root / "Plan.pdf").write_bytes(b"%PDF-1.4\n\xff\xfe binary")
    assert ctx.bridge.read(ctx.project, "Plan.pdf").text is None


def test_read_missing_file_raises_not_found(ctx: Ctx) -> None:
    with pytest.raises(NotFound):
        ctx.bridge.read(ctx.project, "fehlt.md")


@pytest.mark.parametrize(
    "path",
    [
        "../aussen.md",
        "/etc/passwd",
        ".iterthink/settings/project.yaml",
        ".jj/x",
        "Pläne/../../x.md",
        "C:\\x.md",
        ".vscode/tasks.json",
        ".cursor/mcp.json",
        ".github/workflows/x.yml",
        "Pläne/.hidden/x.md",
        "notes/.draft.md",
    ],
)
def test_paths_outside_the_project_are_forbidden(ctx: Ctx, path: str) -> None:
    with pytest.raises(Forbidden):
        ctx.bridge.read(ctx.project, path)
    with pytest.raises(Forbidden):
        ctx.bridge.save(ctx.project, path, "x", ctx.actor)
    with pytest.raises(Forbidden):
        ctx.bridge.propose(ctx.project, {path: "x"}, "agent:t", "test")


def test_files_hides_hidden_files(ctx: Ctx) -> None:
    (ctx.root / ".vscode").mkdir()
    (ctx.root / ".vscode" / "tasks.json").write_text("{}", encoding="utf-8")
    (ctx.root / "Pläne" / ".draft.md").write_text("x", encoding="utf-8")
    paths = {e.path for e in ctx.bridge.files(ctx.project)}
    assert not any(part.startswith(".") for p in paths for part in p.split("/"))


def test_proposal_with_one_hidden_path_is_refused_whole(ctx: Ctx) -> None:
    before = snapshot_sources(ctx.root)
    with pytest.raises(Forbidden):
        ctx.bridge.propose(
            ctx.project, {MD: "# Neu\n", ".cursor/mcp.json": "{}"}, "agent:t", "test"
        )
    assert ctx.bridge.proposals(ctx.project, None) == []
    assert snapshot_sources(ctx.root) == before
    assert not (ctx.root / ".cursor").exists()


def test_save_writes_file_and_creates_version(ctx: Ctx) -> None:
    version = ctx.bridge.save(ctx.project, MD, "# Neu\n", ctx.actor)
    assert version is not None
    assert MD in version.paths
    assert (ctx.root / MD).read_text("utf-8") == "# Neu\n"
    assert ctx.bridge.history(ctx.project, MD)[0].id == version.id


def test_save_unchanged_returns_none(ctx: Ctx) -> None:
    text = (ctx.root / MD).read_text("utf-8")
    assert ctx.bridge.save(ctx.project, MD, text, ctx.actor) is None


def test_save_binary_kind_is_invalid(ctx: Ctx) -> None:
    with pytest.raises(Invalid):
        ctx.bridge.save(ctx.project, "Plan.pdf", "x", ctx.actor)


def test_save_new_file_in_subfolder(ctx: Ctx) -> None:
    ctx.bridge.save(ctx.project, "Notizen/Sitzung 1.md", "# Sitzung\n", ctx.actor)
    assert (ctx.root / "Notizen/Sitzung 1.md").is_file()
    assert "Notizen/Sitzung 1.md" in {e.path for e in ctx.bridge.files(ctx.project)}


def test_save_is_logged_with_actor(ctx: Ctx) -> None:
    ctx.bridge.save(ctx.project, MD, "# Neu\n", ctx.actor)
    entry = ctx.bridge.log(ctx.project)[0]
    assert entry.actor == ctx.actor
    assert MD in entry.summary


# --- history and diff ------------------------------------------------------


def test_history_is_newest_first_and_filtered_by_path(ctx: Ctx) -> None:
    v1 = ctx.bridge.save(ctx.project, MD, "eins\n", ctx.actor)
    v2 = ctx.bridge.save(ctx.project, MD, "zwei\n", ctx.actor)
    ctx.bridge.save(ctx.project, CSV, "id\nT9\n", ctx.actor)
    ids = [v.id for v in ctx.bridge.history(ctx.project, MD)]
    assert v1
    assert v2
    assert ids.index(v2.id) < ids.index(v1.id)
    assert all(MD in v.paths for v in ctx.bridge.history(ctx.project, MD))


def test_text_diff_shows_word_changes(ctx: Ctx) -> None:
    text = (ctx.root / MD).read_text("utf-8").replace("EI30", "EI60")
    ctx.bridge.save(ctx.project, MD, text, ctx.actor)
    diff = ctx.bridge.diff(ctx.project, MD)
    assert diff.kind == "text"
    modified = [b for b in diff.blocks if b.kind != "stable"]
    assert len(modified) == 1
    ops = {(s.op, s.text) for s in modified[0].segments}
    assert ("delete", "EI30.") in ops or any(op == "delete" and "EI30" in t for op, t in ops)
    assert any(op == "insert" and "EI60" in t for op, t in ops)


def test_table_diff_shows_cells_and_rows(ctx: Ctx) -> None:
    ctx.bridge.save(
        ctx.project,
        CSV,
        "id,geschoss,typ,brandschutz\nT01,EG,Holz,EI60\nT03,OG,Holz,EI30\n",
        ctx.actor,
    )
    diff = ctx.bridge.diff(ctx.project, CSV)
    assert diff.kind == "table"
    assert [(c.row, c.column, c.before, c.after) for c in diff.cell_changes] == [
        ("T01", "brandschutz", "EI30", "EI60")
    ]
    assert [r[0] for r in diff.added_rows] == ["T03"]
    assert [r[0] for r in diff.removed_rows] == ["T02"]


def test_diff_between_two_versions(ctx: Ctx) -> None:
    v1 = ctx.bridge.save(ctx.project, MD, "eins\n", ctx.actor)
    v2 = ctx.bridge.save(ctx.project, MD, "zwei\n", ctx.actor)
    assert v1
    assert v2
    diff = ctx.bridge.diff(ctx.project, MD, base=v1.id, target=v2.id)
    assert diff.kind == "text"
    assert diff.summary


def test_restore_brings_back_old_content_and_history_grows(ctx: Ctx) -> None:
    original = (ctx.root / MD).read_text("utf-8")
    first = ctx.bridge.history(ctx.project, MD)[-1]
    ctx.bridge.save(ctx.project, MD, "kaputt\n", ctx.actor)
    count = len(ctx.bridge.history(ctx.project))
    ctx.bridge.restore(ctx.project, MD, first.id, ctx.actor)
    assert (ctx.root / MD).read_text("utf-8") == original
    assert len(ctx.bridge.history(ctx.project)) == count + 1


def test_unknown_version_raises_not_found(ctx: Ctx) -> None:
    with pytest.raises(NotFound):
        ctx.bridge.restore(ctx.project, MD, "v-unknown", ctx.actor)


# --- proposals and verdicts --------------------------------------------------


def _propose_ei60(ctx: Ctx) -> str:
    text = (ctx.root / MD).read_text("utf-8").replace("EI30", "EI60")
    return ctx.bridge.propose(ctx.project, {MD: text}, "agent:checker", "Brandschutz EI60").id


def test_propose_leaves_source_files_untouched(ctx: Ctx) -> None:
    before = snapshot_sources(ctx.root)
    pid = _propose_ei60(ctx)
    assert snapshot_sources(ctx.root) == before
    assert [p.id for p in ctx.bridge.proposals(ctx.project)] == [pid]
    assert {e.path: e.open_proposals for e in ctx.bridge.files(ctx.project)}[MD] == 1


def test_propose_needs_reason_and_changes(ctx: Ctx) -> None:
    with pytest.raises(Invalid):
        ctx.bridge.propose(ctx.project, {MD: "x"}, "agent:t", "  ")
    with pytest.raises(Invalid):
        ctx.bridge.propose(ctx.project, {}, "agent:t", "leer")


def test_proposal_diff_shows_the_change(ctx: Ctx) -> None:
    pid = _propose_ei60(ctx)
    (diff,) = ctx.bridge.proposal_diff(ctx.project, pid)
    assert diff.path == MD
    assert diff.kind == "text"
    assert any(b.kind != "stable" for b in diff.blocks)


def test_accept_applies_change_logs_verdict_and_creates_version(ctx: Ctx) -> None:
    pid = _propose_ei60(ctx)
    version = ctx.bridge.accept(ctx.project, pid, ctx.actor, "passt")
    assert "EI60" in (ctx.root / MD).read_text("utf-8")
    assert MD in version.paths
    (info,) = ctx.bridge.proposals(ctx.project, "accepted")
    assert info.id == pid
    assert info.decided_by == ctx.actor
    entry = ctx.bridge.log(ctx.project)[0]
    assert entry.type == "verdict"
    assert pid in entry.summary
    assert entry.actor == ctx.actor


def test_reject_keeps_file_and_needs_reason(ctx: Ctx) -> None:
    pid = _propose_ei60(ctx)
    before = snapshot_sources(ctx.root)
    with pytest.raises(Invalid):
        ctx.bridge.reject(ctx.project, pid, ctx.actor, "")
    ctx.bridge.reject(ctx.project, pid, ctx.actor, "EI30 reicht")
    assert snapshot_sources(ctx.root) == before
    assert [p.id for p in ctx.bridge.proposals(ctx.project, "rejected")] == [pid]
    assert "EI30 reicht" in ctx.bridge.log(ctx.project)[0].summary


@pytest.mark.parametrize("first", ["accept", "reject"])
def test_deciding_twice_is_a_conflict(ctx: Ctx, first: str) -> None:
    pid = _propose_ei60(ctx)
    if first == "accept":
        ctx.bridge.accept(ctx.project, pid, ctx.actor)
    else:
        ctx.bridge.reject(ctx.project, pid, ctx.actor, "nein")
    with pytest.raises(Conflict):
        ctx.bridge.accept(ctx.project, pid, ctx.actor)
    with pytest.raises(Conflict):
        ctx.bridge.reject(ctx.project, pid, ctx.actor, "nein")


def test_accept_after_conflicting_edit_is_a_conflict_and_changes_nothing(ctx: Ctx) -> None:
    pid = _propose_ei60(ctx)
    edited = (ctx.root / MD).read_text("utf-8").replace("EI30", "EI90")
    ctx.bridge.save(ctx.project, MD, edited, ctx.actor)
    before = snapshot_sources(ctx.root)
    with pytest.raises(Conflict):
        ctx.bridge.accept(ctx.project, pid, ctx.actor)
    assert snapshot_sources(ctx.root) == before
    assert [p.id for p in ctx.bridge.proposals(ctx.project, "conflict")] == [pid]


def test_proposal_can_create_a_new_file(ctx: Ctx) -> None:
    pid = ctx.bridge.propose(ctx.project, {"Neu/Bericht.md": "# Bericht\n"}, "agent:t", "Bericht")
    assert not (ctx.root / "Neu/Bericht.md").exists()
    ctx.bridge.accept(ctx.project, pid.id, ctx.actor)
    assert (ctx.root / "Neu/Bericht.md").read_text("utf-8") == "# Bericht\n"


def test_unknown_proposal_raises_not_found(ctx: Ctx) -> None:
    with pytest.raises(NotFound):
        ctx.bridge.accept(ctx.project, "pr-unknown", ctx.actor)


# --- log, verify, search, vocabulary ----------------------------------------


def test_log_is_newest_first_and_verifies(ctx: Ctx) -> None:
    ctx.bridge.save(ctx.project, MD, "a\n", ctx.actor)
    pid = _propose_ei60(ctx)
    ctx.bridge.reject(ctx.project, pid, ctx.actor, "nein")
    entries = ctx.bridge.log(ctx.project)
    assert [e.seq for e in entries] == sorted((e.seq for e in entries), reverse=True)
    assert len({e.hash for e in entries}) == len(entries)
    result = ctx.bridge.verify(ctx.project)
    assert result.ok
    assert result.lines >= 3
    assert result.error is None


def test_search_is_keyword_and_case_insensitive(ctx: Ctx) -> None:
    hits = ctx.bridge.search(ctx.project, "ei30")
    assert {(h.path, h.line) for h in hits} >= {(MD, 3), (CSV, 2)}
    assert ctx.bridge.search(ctx.project, "   ") == []


def test_search_matches_file_names(ctx: Ctx) -> None:
    assert any(h.path == CSV for h in ctx.bridge.search(ctx.project, "türliste"))


def test_search_kind_keeps_hits_in_files_of_that_kind(ctx: Ctx) -> None:
    hits = ctx.bridge.search(ctx.project, "ei30", kind="table")
    assert hits
    assert {kind_of(h.path) for h in hits} == {"table"}


def test_search_in_history_finds_text_of_earlier_versions(ctx: Ctx) -> None:
    ctx.bridge.save(ctx.project, MD, "Altbau Kellerfenster\n", ctx.actor)
    ctx.bridge.save(ctx.project, MD, "Neubau\n", ctx.actor)
    assert ctx.bridge.search(ctx.project, "kellerfenster") == []
    hits = ctx.bridge.search(ctx.project, "kellerfenster", in_history=True)
    assert {h.path for h in hits} == {MD}


def test_returned_text_has_no_vcs_vocabulary(ctx: Ctx) -> None:
    pid = _propose_ei60(ctx)
    ctx.bridge.save(ctx.project, MD, "a\n", ctx.actor)
    with pytest.raises(Conflict):
        ctx.bridge.accept(ctx.project, pid, ctx.actor)
    texts = [e.summary for e in ctx.bridge.log(ctx.project)]
    texts += [v.message for v in ctx.bridge.history(ctx.project)]
    texts += [d.summary for d in ctx.bridge.proposal_diff(ctx.project, pid)]
    assert not [t for t in texts if VCS_WORDS.search(t)]


def test_kind_of_is_case_insensitive() -> None:
    assert kind_of("A.MD") == "markdown"
    assert kind_of("m.IFC") == "model"
    assert kind_of("x.unknown") == "other"
