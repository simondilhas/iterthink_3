"""Tessellation and placement for an IFC element. Local shape, world box."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, cast

TOL_MM = 1.0
TOL_DEG = 0.01
Matrix = tuple[tuple[float, float, float, float], ...]


@dataclass(frozen=True)
class Mesh:
    verts: tuple[tuple[float, float, float], ...]
    faces: tuple[tuple[int, int, int], ...]


def mesh_of(settings: Any, element: Any) -> Mesh:
    """Triangles for ``element``, or empty when it has no body."""
    import ifcopenshell.geom

    try:
        shape: Any = ifcopenshell.geom.create_shape(settings, element)
    except RuntimeError:
        return Mesh((), ())
    geometry: Any = shape.geometry
    flat = [float(value) for value in geometry.verts]
    verts = tuple((flat[i], flat[i + 1], flat[i + 2]) for i in range(0, len(flat), 3))
    faces = tuple(
        (int(geometry.faces[i]), int(geometry.faces[i + 1]), int(geometry.faces[i + 2]))
        for i in range(0, len(geometry.faces), 3)
    )
    return Mesh(verts, faces)


def shape_hash(mesh: Mesh) -> str:
    """Sha256 of vertices rounded to the 1 mm tolerance, in local coordinates."""
    if not mesh.verts:
        return ""
    rounded = tuple(sorted((round(x, 3), round(y, 3), round(z, 3)) for x, y, z in mesh.verts))
    return hashlib.sha256(repr(rounded).encode("utf-8")).hexdigest()


def bbox_of(mesh: Mesh) -> tuple[float, float, float, float, float, float] | None:
    if not mesh.verts:
        return None
    xs, ys, zs = zip(*mesh.verts, strict=True)
    low = (round(min(xs), 3), round(min(ys), 3), round(min(zs), 3))
    high = (round(max(xs), 3), round(max(ys), 3), round(max(zs), 3))
    return (*low, *high)


def volume_of(mesh: Mesh) -> float | None:
    """Volume in m³ from the tessellated mesh, rounded to 0.001."""
    if not mesh.faces:
        return None
    import numpy as np

    total = 0.0
    for a, b, c in mesh.faces:
        v0, v1, v2 = (np.array(mesh.verts[index]) for index in (a, b, c))
        total += float(np.dot(v0, np.cross(v1, v2)))
    return round(abs(total) / 6.0, 3)


def placement_of(element: Any) -> Matrix | None:
    """The 4×4 placement in millimetres, or None when the element is unplaced."""
    import ifcopenshell.util.placement as placement

    origin = element.ObjectPlacement
    if origin is None:
        return None
    matrix = placement.get_local_placement(origin)
    rows = [tuple(float(item) for item in row) for row in matrix]
    return cast(Matrix, tuple(rows))


def moved(before: Matrix | None, after: Matrix | None) -> bool:
    """True when translation exceeds 1 mm or rotation exceeds 0.01°."""
    if before is None or after is None:
        return before != after
    for index in range(3):
        if abs(before[index][3] - after[index][3]) > TOL_MM:
            return True
    return angle_deg(before, after) > TOL_DEG


def placement_delta(before: Matrix | None, after: Matrix | None) -> dict[str, object]:
    """Translation in mm and rotation in degrees from ``before`` to ``after``."""
    old = before or _identity()
    new = after or _identity()
    shift = [round(new[index][3] - old[index][3], 3) for index in range(3)]
    return {"rotation_deg": round(angle_deg(old, new), 3), "translation_mm": shift}


def angle_deg(before: Matrix, after: Matrix) -> float:
    import numpy as np

    old = np.array(before)[:3, :3]
    new = np.array(after)[:3, :3]
    trace = float(np.trace(new @ old.T))
    cosine = max(-1.0, min(1.0, (trace - 1.0) / 2.0))
    return float(np.degrees(np.arccos(cosine)))


def _identity() -> Matrix:
    return (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )
