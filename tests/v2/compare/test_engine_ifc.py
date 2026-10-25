"""IFC matching, categories and the change contract."""

from __future__ import annotations

import json
import os
from typing import Any, cast

import pytest

try:
    import ifcopenshell  # noqa: F401
except ImportError:
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        pytest.fail("ifcopenshell is required in CI")
    pytest.skip("ifcopenshell extra is not installed", allow_module_level=True)

from iterthink.compare.engine_ifc import IfcEngine, content_changes, ifc_properties, query_ifc
from iterthink.db.change_models import ContentChange
from iterthink.services.bridge import FileDiff

from ..fixtures.ifc_build import Item, build, guid_for

_engine = IfcEngine()


def _diff(before: list[Item], after: list[Item]) -> FileDiff:
    return _engine.diff("model.ifc", build(before), build(after))


def _elements(result: FileDiff) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], result.details["elements"])


def _rows(result: FileDiff) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], result.details["rows"])


def _by_guid(result: FileDiff) -> dict[str, dict[str, Any]]:
    return {row["guid"]: row for row in _elements(result)}


def test_added_removed_changed_by_globalid() -> None:
    kept = Item("kept", name="First")
    gone = Item("gone", name="Same")
    arrived = Item("arrived", name="Same")
    result = _diff([kept, gone], [Item("kept", name="Second"), arrived])
    categories = _by_guid(result)
    assert categories[guid_for("kept")]["category"] not in {"added", "removed"}
    assert categories[guid_for("gone")]["category"] == "removed"
    assert categories[guid_for("arrived")]["category"] == "added"
    assert categories[guid_for("kept")]["name"] == "Second"


def test_each_element_gets_exactly_one_category() -> None:
    before = [
        Item("removed"),
        Item("reshaped", thickness=1),
        Item("moved", x=0),
        Item("props", psets={"Pset_WallCommon": {"FireRating": "EI30"}}),
        Item("same", name="Still"),
    ]
    after = [
        Item("added", name="New"),
        Item("reshaped", thickness=2),
        Item("moved", x=1),
        Item("props", psets={"Pset_WallCommon": {"FireRating": "EI90"}}),
        Item("same", name="Still"),
    ]
    result = _diff(before, after)
    categories = {row["category"] for row in _elements(result)}
    assert categories == {"added", "removed", "reshaped", "moved", "props_only", "unchanged"}
    assert len(_elements(result)) == 6


def test_moved_vs_reshaped() -> None:
    pure = _by_guid(_diff([Item("wall", x=0)], [Item("wall", x=1)]))
    depth = _by_guid(_diff([Item("wall", thickness=1)], [Item("wall", thickness=2)]))
    both = _by_guid(_diff([Item("wall", x=0, thickness=1)], [Item("wall", x=1, thickness=2)]))
    assert pure[guid_for("wall")]["category"] == "moved"
    assert depth[guid_for("wall")]["category"] == "reshaped"
    assert both[guid_for("wall")]["category"] == "reshaped"


def test_within_tolerance_is_unchanged() -> None:
    result = _by_guid(_diff([Item("wall", x=0)], [Item("wall", x=0.0005)]))
    assert result[guid_for("wall")]["category"] == "unchanged"


def test_property_change_has_pset_path() -> None:
    result = _diff(
        [Item("wall", psets={"Pset_WallCommon": {"FireRating": "EI30"}})],
        [Item("wall", psets={"Pset_WallCommon": {"FireRating": "EI90"}})],
    )
    row = next(item for item in _rows(result) if item["path"] == "Pset_WallCommon.FireRating")
    assert row["old"] == "EI30"
    assert row["new"] == "EI90"
    change = next(item for item in content_changes(result) if item.property_path == row["path"])
    assert isinstance(change, ContentChange)
    assert change.change_class == "PropertyChange"
    assert change.affected_subject_id == guid_for("wall")


def test_type_and_attribute_paths() -> None:
    before = [
        Item(
            "wall",
            name="Old",
            type_psets={"Pset_WallCommon": {"IsExternal": True}},
        )
    ]
    after = [
        Item(
            "wall",
            name="New",
            type_psets={"Pset_WallCommon": {"IsExternal": False}},
        )
    ]
    paths = {row["path"]: (row["old"], row["new"]) for row in _rows(_diff(before, after))}
    assert paths["attributes.Name"] == ("Old", "New")
    assert paths["type.Pset_WallCommon.IsExternal"] == ("True", "False")


def test_geometry_rows_map_to_geometry_change() -> None:
    result = _diff(
        [Item("gone"), Item("moved", x=0), Item("reshaped", thickness=1)],
        [Item("added"), Item("moved", x=1), Item("reshaped", thickness=2)],
    )
    rows = {(row["guid"], row["path"]): row for row in _rows(result)}
    assert rows[(guid_for("added"), "geometry.element")]["new"] == "IfcWall"
    assert rows[(guid_for("gone"), "geometry.element")]["old"] == "IfcWall"
    moved = json.loads(rows[(guid_for("moved"), "geometry.placement")]["new"])
    assert moved["translation_mm"][0] == pytest.approx(1000, abs=1)
    shaped = json.loads(rows[(guid_for("reshaped"), "geometry.shape")]["new"])
    assert "volume_before" in shaped
    assert "bbox_after" in shaped
    classes = {item.property_path: item.change_class for item in content_changes(result)}
    assert classes["geometry.element"] == "GeometryChange"
    assert classes["geometry.placement"] == "GeometryChange"
    assert classes["geometry.shape"] == "GeometryChange"


def test_volumes_from_mesh() -> None:
    result = _engine.diff("model.ifc", None, build([Item("box", length=1, height=1, thickness=1)]))
    element = _by_guid(result)[guid_for("box")]
    assert element["volume_after"] == pytest.approx(1.0, abs=0.001)


def test_query_ifc_block_returns_doors_with_pset() -> None:
    data = build(
        [
            Item(
                "door",
                ifc_class="IfcDoor",
                name="D1",
                psets={"Pset_DoorCommon": {"FireRating": "EI90"}},
            ),
            Item("wall", name="W1", psets={"Pset_WallCommon": {"FireRating": "EI30"}}),
        ]
    )
    rows = query_ifc(data, "IfcDoor", ["Pset_DoorCommon"])
    assert len(rows) == 1
    assert rows[0]["Name"] == "D1"
    assert rows[0]["Pset_DoorCommon.FireRating"] == "EI90"
    props = ifc_properties(data, guid_for("door"))
    assert props["Pset_DoorCommon"]["FireRating"] == "EI90"
