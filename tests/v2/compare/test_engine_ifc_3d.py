"""Diff GLB and boolean volumes for a building model."""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import pytest

try:
    import ifcopenshell  # noqa: F401
except ImportError:
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        pytest.fail("ifcopenshell is required in CI")
    pytest.skip("ifcopenshell is not installed", allow_module_level=True)

from iterthink.compare.engine_ifc import IfcEngine
from iterthink.compare.ifc_glb import store_glbs

from ..fixtures.ifc_build import Item, build, guid_for


def _diff(before: list[Item], after: list[Item], cache: Path) -> dict[str, object]:
    result = IfcEngine().diff("model.ifc", build(before), build(after), cache=cache)
    return dict(result.details)


def _by_guid(details: dict[str, object]) -> dict[str, dict[str, object]]:
    raw = details["elements"]
    assert isinstance(raw, list)
    found: dict[str, dict[str, object]] = {}
    for item in raw:
        assert isinstance(item, dict)
        found[str(item["guid"])] = item
    return found


def _nodes(path: Path) -> list[dict[str, object]]:
    data = path.read_bytes()
    assert data[:4] == b"glTF"
    size, kind = struct.unpack_from("<II", data, 12)
    assert kind == 0x4E4F534A
    parsed = json.loads(data[20 : 20 + size].rstrip(b" "))
    assert isinstance(parsed, dict)
    nodes = parsed["nodes"]
    assert isinstance(nodes, list)
    return [node for node in nodes if isinstance(node, dict)]


def test_boolean_difference_volumes(tmp_path: Path) -> None:
    details = _diff(
        [Item("wall", length=1, height=2, thickness=0.2)],
        [Item("wall", length=2, height=2, thickness=0.2)],
        tmp_path / "cache",
    )
    element = _by_guid(details)[guid_for("wall")]
    assert element["diff_method"] == "boolean"
    assert element["volume_added"] == pytest.approx(0.4, abs=0.02)
    assert element["volume_removed"] == 0.0


def test_boolean_failure_falls_back_to_overlay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> tuple[object, object]:
        raise RuntimeError("kernel")

    monkeypatch.setattr("iterthink.compare.ifc_glb.boolean_difference", boom)
    details = _diff(
        [Item("wall", length=1), Item("other", name="Keep")],
        [Item("wall", length=2), Item("other", name="Keep"), Item("added", name="New")],
        tmp_path / "cache",
    )
    elements = _by_guid(details)
    assert elements[guid_for("wall")]["diff_method"] == "overlay"
    assert elements[guid_for("other")]["category"] == "unchanged"
    assert elements[guid_for("added")]["category"] == "added"


def test_diff_glb_nodes_carry_guid_category_part(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    details = _diff([Item("wall", length=1)], [Item("wall", length=2)], cache)
    glb = details["glb"]
    assert isinstance(glb, dict)
    diff_path = cache / str(glb["key"]) / "diff.glb"
    nodes = _nodes(diff_path)
    elements = _by_guid(details)
    assert nodes
    parts: set[str] = set()
    for node in nodes:
        guid = str(node["name"])
        extras = node["extras"]
        assert isinstance(extras, dict)
        assert extras["category"] == elements[guid]["category"]
        part = str(extras["part"])
        assert part in {"after", "before", "added_volume", "removed_volume"}
        parts.add(part)
    assert "added_volume" in parts
    assert "after" in parts


def test_glb_cached_outside_project(tmp_path: Path) -> None:
    project = tmp_path / "P-101"
    project.mkdir()
    before = build([Item("wall", length=1)])
    after = build([Item("wall", length=2)])
    (project / "model.ifc").write_bytes(after)
    cache = tmp_path / "state"
    first = store_glbs(before, after, cache)
    stamp = first.stat().st_mtime_ns
    second = store_glbs(before, after, cache)
    assert second == first
    assert second.stat().st_mtime_ns == stamp
    assert [path.name for path in project.rglob("*") if path.is_file()] == ["model.ifc"]


def test_diff_counts_matches_and_booleans(tmp_path: Path) -> None:
    from iterthink.compare.ifc_progress import counters, key_of

    before = build([Item("wall", length=1), Item("door")])
    after = build([Item("wall", length=2), Item("door"), Item("new")])
    IfcEngine().diff("model.ifc", before, after, cache=tmp_path / "cache")
    assert counters(key_of(before, after)) == {
        "elements": 3,
        "matched": 3,
        "reshaped": 1,
        "booleans": 1,
        "fallbacks": 0,
        "done": 1,
    }
    assert counters(key_of(after, before)) == {}
