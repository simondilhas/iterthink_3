"""Small IFC models for the engine tests. One box per element, matched by a stable id."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Any

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.type
import ifcopenshell.api.unit
import ifcopenshell.guid


@dataclass
class Item:
    """One element. ``key`` becomes the same GlobalId in every file that uses it."""

    key: str
    ifc_class: str = "IfcWall"
    name: str = "Element"
    storey: str = "Ground"
    length: float = 1.0
    height: float = 1.0
    thickness: float = 1.0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    rz: float = 0.0
    psets: dict[str, dict[str, object]] = field(default_factory=dict)
    type_psets: dict[str, dict[str, object]] = field(default_factory=dict)
    geometry: bool = True


def guid_for(key: str) -> str:
    """A stable GlobalId for ``key``."""
    return str(ifcopenshell.guid.compress(str(uuid.uuid5(uuid.NAMESPACE_URL, f"iterthink:{key}"))))


def build(items: list[Item]) -> bytes:
    """STEP bytes for ``items``."""
    model = ifcopenshell.api.project.create_file(version="IFC4")
    project = ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="Test")
    ifcopenshell.api.unit.assign_unit(model)
    body = _body(model)
    storeys = _storeys(model, project, sorted({item.storey for item in items}))
    for item in items:
        _add(model, body, storeys[item.storey], item)
    return str(model.to_string()).encode("utf-8")


def _body(model: Any) -> Any:
    context = ifcopenshell.api.context.add_context(model, context_type="Model")
    return ifcopenshell.api.context.add_context(
        model,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=context,
    )


def _storeys(model: Any, project: Any, names: list[str]) -> dict[str, Any]:
    site = ifcopenshell.api.root.create_entity(model, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuilding", name="Building")
    ifcopenshell.api.aggregate.assign_object(model, relating_object=project, products=[site])
    ifcopenshell.api.aggregate.assign_object(model, relating_object=site, products=[building])
    found: dict[str, object] = {}
    for name in names:
        storey = ifcopenshell.api.root.create_entity(
            model, ifc_class="IfcBuildingStorey", name=name
        )
        ifcopenshell.api.aggregate.assign_object(model, relating_object=building, products=[storey])
        found[name] = storey
    return found


def _add(model: Any, body: Any, storey: Any, item: Item) -> None:
    element = ifcopenshell.api.root.create_entity(model, ifc_class=item.ifc_class, name=item.name)
    element.GlobalId = guid_for(item.key)
    ifcopenshell.api.spatial.assign_container(model, relating_structure=storey, products=[element])
    if item.geometry:
        rep = ifcopenshell.api.geometry.add_wall_representation(
            model, context=body, length=item.length, height=item.height, thickness=item.thickness
        )
        ifcopenshell.api.geometry.assign_representation(model, product=element, representation=rep)
        ifcopenshell.api.geometry.edit_object_placement(
            model, product=element, matrix=cast_matrix(item)
        )
    for name, props in item.psets.items():
        pset = ifcopenshell.api.pset.add_pset(model, product=element, name=name)
        ifcopenshell.api.pset.edit_pset(model, pset=pset, properties=dict(props))
    if item.type_psets:
        kind = "IfcDoorType" if item.ifc_class == "IfcDoor" else "IfcWallType"
        typed = ifcopenshell.api.root.create_entity(model, ifc_class=kind, name=f"{item.name} type")
        for name, props in item.type_psets.items():
            pset = ifcopenshell.api.pset.add_pset(model, product=typed, name=name)
            ifcopenshell.api.pset.edit_pset(model, pset=pset, properties=dict(props))
        ifcopenshell.api.type.assign_type(model, related_objects=[element], relating_type=typed)


def cast_matrix(item: Item) -> Any:
    return _matrix(item)


def _matrix(item: Item) -> list[list[float]]:
    angle = math.radians(item.rz)
    cosine, sine = math.cos(angle), math.sin(angle)
    return [
        [cosine, -sine, 0.0, item.x],
        [sine, cosine, 0.0, item.y],
        [0.0, 0.0, 1.0, item.z],
        [0.0, 0.0, 0.0, 1.0],
    ]
