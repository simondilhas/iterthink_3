"""The model table, a proposal, and the example apps."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

try:
    import ifcopenshell  # noqa: F401
except ImportError:
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        pytest.fail("ifcopenshell is required in CI")
    pytest.skip("ifcopenshell extra is not installed", allow_module_level=True)

from iterthink.persistence.snapshots import Snapshots
from iterthink.services.app_validate import problems
from iterthink.services.bridge_real import RealBridge
from iterthink.services.event_log import utc_now
from iterthink.services.projects import tracked_files
from iterthink.services.proposals import create as create_proposal
from iterthink.web.app import TOKEN_HEADER, create_app

from ..fixtures.ifc_build import Item, build

_HEADERS = {TOKEN_HEADER: "token"}


def _bridge(tmp_path: Path, project_dir: Path) -> tuple[RealBridge, str]:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    return bridge, bridge.make_project(project_dir).id


def _version(project_dir: Path, data: bytes, message: str) -> str:
    (project_dir / "model.ifc").write_bytes(data)
    version = Snapshots(project_dir).snapshot(tracked_files(project_dir), message, "user:ada")
    assert version is not None
    return version.id


def test_metadata_table_one_row_per_property(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    common = {"AcousticRating": "40"}
    old = build([Item("wall", psets={"Pset_WallCommon": {"FireRating": "EI30", **common}})])
    new = build([Item("wall", psets={"Pset_WallCommon": {"FireRating": "EI90", **common}})])
    base = _version(project_dir, old, "first model")
    target = _version(project_dir, new, "second model")
    client = TestClient(create_app(bridge=bridge, token="token", actor="user:ada"))
    page = client.get(
        f"/p/{project}/models/compare",
        params={
            "path": "model.ifc",
            "from": base,
            "to": target,
            "category": "props_only",
            "pset": "Pset_WallCommon",
        },
        headers=_HEADERS,
    )
    assert page.status_code == 200
    assert "Pset_WallCommon.FireRating" in page.text
    assert "EI30" in page.text
    assert "EI90" in page.text
    assert "AcousticRating" not in page.text
    assert "<ins>" in page.text
    assert "<del>" in page.text
    fragment = client.get(
        f"/p/{project}/models/compare",
        params={"path": "model.ifc", "from": base, "to": target, "sort": "path"},
        headers={**_HEADERS, "HX-Request": "true"},
    )
    assert fragment.status_code == 200
    assert "model-table" in fragment.text
    assert "<html" not in fragment.text.lower()


def test_review_uses_model_partial_for_ifc_proposal(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    old = build([Item("wall", psets={"Pset_WallCommon": {"FireRating": "EI30"}})])
    new = build([Item("wall", psets={"Pset_WallCommon": {"FireRating": "EI90"}})])
    _version(project_dir, old, "first model")
    made = create_proposal(
        project_dir,
        Snapshots(project_dir),
        machine="m-test",
        project=project,
        changes={"model.ifc": new.decode("utf-8")},
        actor="user:ada",
        reason="update the rating",
        baseline=None,
        now=utc_now,
    )
    client = TestClient(create_app(bridge=bridge, token="token", actor="user:ada"))
    page = client.get(f"/p/{project}/proposals/{made.id}", headers=_HEADERS)
    assert page.status_code == 200
    assert 'data-read-only="model"' in page.text
    assert "Pset_WallCommon.FireRating" in page.text
    assert "<ins>" in page.text
    assert "/changes/" not in page.text


def test_example_apps_run(tmp_path: Path, project_dir: Path) -> None:
    bridge, project = _bridge(tmp_path, project_dir)
    door = Item(
        "door",
        ifc_class="IfcDoor",
        name="D1",
        psets={"Pset_DoorCommon": {"FireRating": "EI90"}},
    )
    _version(project_dir, build([door]), "doors")
    for slug in ("door-schedule", "fire-rating"):
        bridge.install_example(project, slug)
        page = project_dir / ".iterthink" / "apps" / slug / "index.html"
        html = page.read_text(encoding="utf-8")
        assert problems(html) == []
    rows = bridge.app_call(
        project,
        "door-schedule",
        "queryIfc",
        {"path": "model.ifc", "ifc_class": "IfcDoor", "psets": ["Pset_DoorCommon"]},
        "user:ada",
    )
    assert isinstance(rows, list)
    assert rows[0]["Name"] == "D1"
    assert rows[0]["Pset_DoorCommon.FireRating"] == "EI90"
    props = bridge.app_call(
        project,
        "fire-rating",
        "ifcProperties",
        {"path": "model.ifc", "guid": rows[0]["GlobalId"]},
        "user:ada",
    )
    assert isinstance(props, dict)
    assert props["Pset_DoorCommon"]["FireRating"] == "EI90"
    hits = bridge.app_call(project, "fire-rating", "search", {"query": "EI30"}, "user:ada")
    assert isinstance(hits, list)
    assert hits
