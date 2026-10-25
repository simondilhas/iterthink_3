"""IFC models. Elements match by GlobalId. One category each, then one table."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from iterthink.compare.engine_ifc_geom import (
    Matrix,
    bbox_of,
    mesh_of,
    moved,
    placement_delta,
    placement_of,
    shape_hash,
    volume_of,
)
from iterthink.db.change_models import ContentChange
from iterthink.services.bridge import FileDiff, FileKind

_CATEGORIES = ("added", "removed", "reshaped", "moved", "props_only", "unchanged")
_ATTRS = ("Name", "Description", "Tag", "ObjectType")
_GEOM = {
    "added": "geometry.element",
    "removed": "geometry.element",
    "moved": "geometry.placement",
    "reshaped": "geometry.shape",
}


@dataclass(frozen=True)
class Element:
    """One element read from one version."""

    guid: str
    ifc_class: str
    name: str
    storey: str
    psets: dict[str, dict[str, str]]
    type_psets: dict[str, dict[str, str]]
    attributes: dict[str, str]
    shape: str
    placement: Matrix | None
    bbox: tuple[float, float, float, float, float, float] | None
    volume: float | None


class IfcEngine:
    """Diff an ``.ifc`` file by GlobalId."""

    kinds: tuple[FileKind, ...] = ("model",)

    def diff(self, path: str, before: bytes | None, after: bytes | None) -> FileDiff:
        old, new = _read(before), _read(after)
        elements, rows = _compare(old, new)
        counts = {name: 0 for name in _CATEGORIES}
        for item in elements:
            counts[str(item["category"])] += 1
        changed = sum(counts[name] for name in _CATEGORIES if name != "unchanged")
        summary = "no changes" if changed == 0 else f"{changed} elements changed"
        return FileDiff(
            path,
            "model",
            summary,
            details={"elements": elements, "counts": counts, "rows": rows},
        )


def content_changes(diff: FileDiff) -> list[ContentChange]:
    """Map the table onto the change contract. Geometry and properties stay apart."""
    raw = diff.details.get("rows", [])
    rows = raw if isinstance(raw, list) else []
    made: list[ContentChange] = []
    for row in rows:
        if isinstance(row, dict):
            made.append(_change(row))
    return made


def query_ifc(data: bytes, ifc_class: str, psets: list[str]) -> list[dict[str, str]]:
    """Rows for one class, with the named property sets flattened onto each row."""
    found: list[dict[str, str]] = []
    for element in _read(data).values():
        if ifc_class and element.ifc_class != ifc_class:
            continue
        row = {
            "GlobalId": element.guid,
            "class": element.ifc_class,
            "Name": element.name,
            "storey": element.storey,
        }
        for name in psets:
            props = element.psets.get(name) or element.type_psets.get(name) or {}
            for key, value in props.items():
                row[f"{name}.{key}"] = value
        found.append(row)
    return found


def ifc_properties(data: bytes, guid: str) -> dict[str, dict[str, str]]:
    """Property sets on one element. Inherited values are under ``type.<pset>``."""
    element = _read(data).get(guid)
    if element is None:
        return {}
    found = {name: dict(props) for name, props in element.psets.items()}
    for name, props in _inherited(element).items():
        found[f"type.{name}"] = props
    return found


def _change(row: dict[str, object]) -> ContentChange:
    path = str(row.get("path", ""))
    kind = "GeometryChange" if path.startswith("geometry.") else "PropertyChange"
    return ContentChange(
        content_version_id=0,
        lineage_id=str(row.get("guid", "")),
        change_class=kind,
        change_type=str(row.get("category", "")),
        from_revision=0,
        to_revision=1,
        affected_subject_id=str(row.get("guid", "")),
        affected_subject_type=str(row.get("class", "")),
        property_path=path,
        from_value=_or_none(row.get("old")),
        to_value=_or_none(row.get("new")),
    )


def _or_none(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _read(data: bytes | None) -> dict[str, Element]:
    if not data:
        return {}
    import ifcopenshell
    import ifcopenshell.geom

    model: Any = ifcopenshell.file.from_string(data.decode("utf-8"))
    local = ifcopenshell.geom.settings()
    world = ifcopenshell.geom.settings()
    local.set("use-world-coords", False)
    world.set("use-world-coords", True)
    found: dict[str, Element] = {}
    for element in model.by_type("IfcElement"):
        if _skip(element):
            continue
        item = _element(element, local, world)
        found[item.guid] = item
    return found


def _skip(element: Any) -> bool:
    return bool(element.is_a("IfcOpeningElement") or element.is_a("IfcSpace"))


def _element(element: Any, local: Any, world: Any) -> Element:
    mesh = mesh_of(local, element)
    placed = mesh_of(world, element)
    return Element(
        guid=str(element.GlobalId),
        ifc_class=str(element.is_a()),
        name=_text(element.Name),
        storey=_storey(element),
        psets=_psets(element, inherit=False),
        type_psets=_type_psets(element),
        attributes=_attributes(element),
        shape=shape_hash(mesh),
        placement=placement_of(element),
        bbox=bbox_of(placed),
        volume=volume_of(mesh),
    )


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _storey(element: Any) -> str:
    import ifcopenshell.util.element as util

    container = cast(Any, util.get_container(element))
    if container is None:
        return ""
    return _text(container.Name)


def _psets(element: Any, *, inherit: bool) -> dict[str, dict[str, str]]:
    import ifcopenshell.util.element as util

    raw = cast(dict[object, object], util.get_psets(element, should_inherit=inherit) or {})
    return {str(name): _props(value) for name, value in raw.items()}


def _props(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items() if key != "id"}


def _type_psets(element: Any) -> dict[str, dict[str, str]]:
    import ifcopenshell.util.element as util

    typed = cast(object | None, util.get_type(element))
    if typed is None:
        return {}
    return _psets(typed, inherit=False)


def _attributes(element: Any) -> dict[str, str]:
    found = {"class": str(element.is_a())}
    for name in _ATTRS:
        found[name] = _text(getattr(element, name, None))
    return found


def _compare(
    old: dict[str, Element], new: dict[str, Element]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    elements: list[dict[str, object]] = []
    rows: list[dict[str, object]] = []
    for guid in sorted(set(old) | set(new)):
        before, after = old.get(guid), new.get(guid)
        category = _category(before, after)
        current = after or before
        assert current is not None
        prop_rows = _prop_rows(before, after, category)
        elements.append(_card(current, before, after, category, bool(prop_rows)))
        rows.extend(prop_rows)
        geometric = _geom_row(current, before, after, category)
        if geometric is not None:
            rows.append(geometric)
    return elements, rows


def _category(before: Element | None, after: Element | None) -> str:
    if before is None:
        return "added"
    if after is None:
        return "removed"
    if before.shape != after.shape:
        return "reshaped"
    if moved(before.placement, after.placement):
        return "moved"
    if _prop_rows(before, after, "props_only"):
        return "props_only"
    return "unchanged"


def _card(
    current: Element,
    before: Element | None,
    after: Element | None,
    category: str,
    props: bool,
) -> dict[str, object]:
    return {
        "guid": current.guid,
        "class": current.ifc_class,
        "name": (after or before or current).name,
        "storey": current.storey,
        "category": category,
        "has_property_changes": props,
        "bbox_before": None if before is None else before.bbox,
        "bbox_after": None if after is None else after.bbox,
        "placement_delta": _delta(before, after) if category == "moved" else None,
        "volume_before": None if before is None else before.volume,
        "volume_after": None if after is None else after.volume,
    }


def _inherited(element: Element) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for name, props in element.type_psets.items():
        own = element.psets.get(name, {})
        kept = {key: value for key, value in props.items() if key not in own}
        if kept:
            found[name] = kept
    return found


def _values(element: Element | None) -> dict[str, str]:
    if element is None:
        return {}
    found = {f"attributes.{name}": value for name, value in element.attributes.items()}
    for name, props in element.psets.items():
        for key, value in props.items():
            found[f"{name}.{key}"] = value
    for name, props in _inherited(element).items():
        for key, value in props.items():
            found[f"type.{name}.{key}"] = value
    return found


def _prop_rows(
    before: Element | None, after: Element | None, category: str
) -> list[dict[str, object]]:
    old, new = _values(before), _values(after)
    current = after or before
    assert current is not None
    rows: list[dict[str, object]] = []
    for path in sorted(set(old) | set(new)):
        if old.get(path, "") == new.get(path, ""):
            continue
        rows.append(_row(current, category, path, old.get(path, ""), new.get(path, "")))
    return rows


def _geom_row(
    current: Element, before: Element | None, after: Element | None, category: str
) -> dict[str, object] | None:
    path = _GEOM.get(category)
    if path is None:
        return None
    if category == "added":
        return _row(current, category, path, "", current.ifc_class)
    if category == "removed":
        return _row(current, category, path, current.ifc_class, "")
    payload = _delta(before, after) if category == "moved" else _shape_payload(before, after)
    return _row(current, category, path, "", json.dumps(payload, sort_keys=True))


def _row(element: Element, category: str, path: str, old: str, new: str) -> dict[str, object]:
    return {
        "guid": element.guid,
        "class": element.ifc_class,
        "name": element.name,
        "storey": element.storey,
        "category": category,
        "path": path,
        "old": old,
        "new": new,
    }


def _delta(before: Element | None, after: Element | None) -> dict[str, object]:
    old = before.placement if before else None
    new = after.placement if after else None
    return placement_delta(old, new)


def _shape_payload(before: Element | None, after: Element | None) -> dict[str, object]:
    return {
        "bbox_after": None if after is None else after.bbox,
        "bbox_before": None if before is None else before.bbox,
        "volume_after": None if after is None else after.volume,
        "volume_before": None if before is None else before.volume,
    }
