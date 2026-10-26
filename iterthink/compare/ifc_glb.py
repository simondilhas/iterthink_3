"""GLB for one model version and for a pair. Cached beside the project, not in it."""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from typing import Any

import numpy as np

from iterthink.compare.engine_ifc_geom import Mesh, mesh_of, volume_of
from iterthink.compare.ifc_progress import bump, set_count
from iterthink.compare.ifc_progress import key_of as _key

_MAX_TRIANGLES = 50_000
_JSON = 0x4E4F534A
_BIN = 0x004E4942
_HEX = re.compile(r"[0-9a-f]{64}")
Part = tuple[str, str, str, Mesh]


def write_glb(parts: list[tuple[str, dict[str, str], np.ndarray, np.ndarray]]) -> bytes:
    """One glTF 2.0 binary. Node names and extras are preserved."""
    blobs = bytearray()
    nodes: list[dict[str, object]] = []
    meshes: list[dict[str, object]] = []
    accessors: list[dict[str, object]] = []
    views: list[dict[str, object]] = []
    for name, extras, verts, faces in parts:
        mesh_index = _pack(blobs, views, accessors, verts, faces)
        primitive = {"attributes": {"POSITION": mesh_index}, "indices": mesh_index + 1}
        meshes.append({"primitives": [primitive]})
        nodes.append({"name": name, "mesh": len(meshes) - 1, "extras": extras})
    document = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(blobs)}],
    }
    return _container(document, bytes(blobs))


def store_glbs(before: bytes | None, after: bytes | None, cache: Path) -> Path:
    """Write the diff GLB. A second call for the same bytes does not render again."""
    folder = cache / _key(before, after)
    dest = folder / "diff.glb"
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    _emit(folder / "before.glb", _version_parts(before))
    _emit(folder / "after.glb", _version_parts(after))
    _emit(dest, _diff_parts(before, after, None))
    return dest


def attach(
    before: bytes | None, after: bytes | None, elements: list[dict[str, object]], cache: Path | None
) -> dict[str, str]:
    """Record volumes on ``elements`` and the URLs of the three GLBs."""
    key = _key(before, after)
    _volumes(before, after, elements, key)
    folder = (cache if cache is not None else _default_cache()) / key
    if not (folder / "diff.glb").is_file():
        _emit(folder / "before.glb", _version_parts(before))
        _emit(folder / "after.glb", _version_parts(after))
        _emit(folder / "diff.glb", _diff_parts(before, after, elements))
    return {
        "key": key,
        "before": f"/models/glb/{key}/before.glb" if before else "",
        "after": f"/models/glb/{key}/after.glb" if after else "",
        "diff": f"/models/glb/{key}/diff.glb",
    }


def cached(key: str, part: str, cache: Path | None = None) -> bytes | None:
    """Bytes of a GLB that ``attach`` wrote, or None for an unknown key or part."""
    if part not in ("before", "after", "diff") or not _HEX.fullmatch(key):
        return None
    path = (cache if cache is not None else _default_cache()) / key / f"{part}.glb"
    return path.read_bytes() if path.is_file() else None


def boolean_difference(before: bytes, after: bytes, guid: str) -> tuple[Mesh, Mesh]:
    """Added solid is after minus before. Removed solid is before minus after."""
    return _subtract(after, before, guid), _subtract(before, after, guid)


def _default_cache() -> Path:
    from iterthink.services.projects import default_state_dir

    return default_state_dir() / "ifc-glb"


def _emit(path: Path, parts: list[Part]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [_ready(part) for part in parts]
    written = [item for item in payload if item[2].size and item[3].size]
    temporary = path.with_suffix(".glb.tmp")
    temporary.write_bytes(write_glb(written))
    temporary.replace(path)


def _ready(part: Part) -> tuple[str, dict[str, str], np.ndarray, np.ndarray]:
    guid, category, role, mesh = part
    verts, faces = _arrays(mesh)
    return guid, {"category": category, "part": role}, verts, faces


def _arrays(mesh: Mesh) -> tuple[np.ndarray, np.ndarray]:
    if not mesh.verts or not mesh.faces:
        return np.zeros((0, 3), np.float32), np.zeros((0, 3), np.uint32)
    return np.array(mesh.verts, dtype=np.float32), np.array(mesh.faces, dtype=np.uint32)


def _volumes(
    before: bytes | None, after: bytes | None, elements: list[dict[str, object]], key: str
) -> None:
    reshaped = sum(1 for element in elements if element.get("category") == "reshaped")
    set_count(key, "reshaped", reshaped if before is not None and after is not None else 0)
    for element in elements:
        element["volume_added"] = None
        element["volume_removed"] = None
        element["diff_method"] = None
        if element.get("category") != "reshaped" or before is None or after is None:
            continue
        guid = str(element["guid"])
        try:
            if _heavy(before, guid) or _heavy(after, guid):
                raise RuntimeError("too many triangles")
            added, removed = boolean_difference(before, after, guid)
        except Exception:
            element["diff_method"] = "overlay"
            bump(key, "fallbacks")
            continue
        bump(key, "booleans")
        element["diff_method"] = "boolean"
        element["volume_added"] = _metres(added)
        element["volume_removed"] = _metres(removed)


def _metres(mesh: Mesh) -> float:
    measured = volume_of(mesh)
    return 0.0 if measured is None else measured


def _diff_parts(
    before: bytes | None, after: bytes | None, elements: list[dict[str, object]] | None
) -> list[Part]:
    rows = elements if elements is not None else _plain(before, after)
    parts: list[Part] = []
    for element in rows:
        parts.extend(_element_parts(before, after, element))
    return parts


def _plain(before: bytes | None, after: bytes | None) -> list[dict[str, object]]:
    guids = _guids(before) | _guids(after)
    return [{"guid": guid, "category": "unchanged", "diff_method": None} for guid in sorted(guids)]


def _element_parts(
    before: bytes | None, after: bytes | None, element: dict[str, object]
) -> list[Part]:
    guid = str(element["guid"])
    category = str(element.get("category") or "unchanged")
    method = element.get("diff_method")
    after_mesh = _world(after, guid)
    before_mesh = _world(before, guid)
    if category == "removed":
        return [(guid, category, "before", before_mesh)]
    if category == "moved" or (category == "reshaped" and method == "overlay"):
        return [(guid, category, "after", after_mesh), (guid, category, "before", before_mesh)]
    parts = [(guid, category, "after", after_mesh)]
    if category == "reshaped" and method == "boolean" and before is not None and after is not None:
        parts.extend(_volume_parts(before, after, guid, category))
    return parts


def _volume_parts(before: bytes, after: bytes, guid: str, category: str) -> list[Part]:
    try:
        added, removed = boolean_difference(before, after, guid)
    except Exception:
        return []
    found = [(guid, category, "added_volume", added)]
    if removed.faces:
        found.append((guid, category, "removed_volume", removed))
    return found


def _version_parts(data: bytes | None) -> list[Part]:
    model = _open(data)
    indexed = _elements(model)
    return [(guid, "unchanged", "after", _mesh(element)) for guid, element in indexed.items()]


def _world(data: bytes | None, guid: str) -> Mesh:
    """World mesh. The file stays referenced until tessellation returns."""
    model = _open(data)
    return _mesh(_elements(model).get(guid))


def _heavy(data: bytes, guid: str) -> bool:
    return len(_world(data, guid).faces) > _MAX_TRIANGLES


def _mesh(element: Any) -> Mesh:
    if element is None:
        return Mesh((), ())
    import ifcopenshell.geom

    settings: Any = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    return mesh_of(settings, element)


def _guids(data: bytes | None) -> set[str]:
    return set(_elements(_open(data)))


def _open(data: bytes | None) -> Any:
    if not data:
        return None
    import ifcopenshell

    return ifcopenshell.file.from_string(data.decode("utf-8"))


def _elements(model: Any) -> dict[str, Any]:
    if model is None:
        return {}
    found: dict[str, Any] = {}
    for element in model.by_type("IfcElement"):
        if element.is_a("IfcOpeningElement") or element.is_a("IfcSpace"):
            continue
        found[str(element.GlobalId)] = element
    return found


def _subtract(source: bytes, other: bytes, guid: str) -> Mesh:
    import ifcopenshell
    import ifcopenshell.api.geometry
    import ifcopenshell.api.root

    host: Any = ifcopenshell.file.from_string(source.decode("utf-8"))
    guest: Any = ifcopenshell.file.from_string(other.decode("utf-8"))
    first_el = next(item for item in host.by_type("IfcElement") if str(item.GlobalId) == guid)
    second_el = next(item for item in guest.by_type("IfcElement") if str(item.GlobalId) == guid)
    first = _item(first_el)
    second = host.add(_item(second_el))
    _bake(first, first_el)
    _bake(second, second_el)
    made = ifcopenshell.api.geometry.add_boolean(
        host, first_item=first, second_items=[second], operator="DIFFERENCE"
    )
    if not made:
        raise RuntimeError("empty boolean")
    return _tessellate(host, made[0], ifcopenshell.api.root)


def _item(element: Any) -> Any:
    reps = element.Representation.Representations if element.Representation else []
    for rep in reps:
        for item in rep.Items:
            if item.is_a("IfcBooleanResult") or item.is_a("IfcSolidModel"):
                return item
    raise RuntimeError("no solid")


def _bake(solid: Any, element: Any) -> None:
    if not _bare(solid) or element.ObjectPlacement is None:
        return
    import ifcopenshell.util.placement as placement

    matrix = placement.get_local_placement(element.ObjectPlacement)
    file = solid.file
    point = file.createIfcCartesianPoint([float(matrix[i][3]) for i in range(3)])
    axis = file.createIfcDirection([float(matrix[i][2]) for i in range(3)])
    ref = file.createIfcDirection([float(matrix[i][0]) for i in range(3)])
    solid.Position = file.createIfcAxis2Placement3D(point, axis, ref)


def _bare(solid: Any) -> bool:
    position = getattr(solid, "Position", None)
    if position is None or position.Location is None:
        return True
    return all(abs(float(value)) < 1e-6 for value in position.Location.Coordinates)


def _tessellate(model: Any, boolean: Any, root: Any) -> Mesh:
    contexts = model.by_type("IfcGeometricRepresentationSubContext")
    if not contexts:
        raise RuntimeError("no body context")
    wall = root.create_entity(model, ifc_class="IfcBuildingElementProxy", name="Diff")
    rep = model.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=contexts[0],
        RepresentationIdentifier="Body",
        RepresentationType="CSG",
        Items=[boolean],
    )
    import ifcopenshell.api.geometry

    ifcopenshell.api.geometry.assign_representation(model, product=wall, representation=rep)
    ifcopenshell.api.geometry.edit_object_placement(model, product=wall)
    return _mesh(wall)


def _pack(
    blobs: bytearray,
    views: list[dict[str, object]],
    accessors: list[dict[str, object]],
    verts: np.ndarray,
    faces: np.ndarray,
) -> int:
    start = _align(blobs)
    raw = np.ascontiguousarray(verts, dtype=np.float32).tobytes()
    blobs.extend(raw)
    views.append({"buffer": 0, "byteOffset": start, "byteLength": len(raw), "target": 34962})
    low = verts.min(axis=0).tolist()
    high = verts.max(axis=0).tolist()
    accessors.append(
        {
            "bufferView": len(views) - 1,
            "componentType": 5126,
            "count": len(verts),
            "type": "VEC3",
            "min": low,
            "max": high,
        }
    )
    face_at = _align(blobs)
    face_raw = np.ascontiguousarray(faces, dtype=np.uint32).tobytes()
    blobs.extend(face_raw)
    views.append({"buffer": 0, "byteOffset": face_at, "byteLength": len(face_raw), "target": 34963})
    accessors.append(
        {
            "bufferView": len(views) - 1,
            "componentType": 5125,
            "count": int(faces.size),
            "type": "SCALAR",
        }
    )
    return len(accessors) - 2


def _align(blobs: bytearray) -> int:
    while len(blobs) % 4:
        blobs.append(0)
    return len(blobs)


def _container(document: dict[str, object], binary: bytes) -> bytes:
    text = _pad(json.dumps(document, separators=(",", ":")).encode("utf-8"), b" ")
    blob = _pad(binary, b"\x00")
    body = struct.pack("<II", len(text), _JSON) + text + struct.pack("<II", len(blob), _BIN) + blob
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def _pad(data: bytes, fill: bytes) -> bytes:
    extra = (4 - len(data) % 4) % 4
    return data + fill * extra
