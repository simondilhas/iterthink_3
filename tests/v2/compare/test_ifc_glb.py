"""glTF binary writer: header, chunks, and a cache outside the project."""

from __future__ import annotations

import json
import struct

import numpy as np

from iterthink.compare.ifc_glb import write_glb


def _chunks(data: bytes) -> tuple[dict[str, object], bytes]:
    assert data[:4] == b"glTF"
    version, length = struct.unpack_from("<II", data, 4)
    assert version == 2
    assert length == len(data)
    offset = 12
    json_chunk = b""
    binary = b""
    while offset < len(data):
        size, kind = struct.unpack_from("<II", data, offset)
        offset += 8
        payload = data[offset : offset + size]
        offset += size
        assert size % 4 == 0
        if kind == 0x4E4F534A:
            json_chunk = payload.rstrip(b" ")
        elif kind == 0x004E4942:
            binary = payload
    parsed = json.loads(json_chunk)
    assert isinstance(parsed, dict)
    return parsed, binary


def test_glb_writer_roundtrip() -> None:
    verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    faces = np.array([[0, 1, 2]], dtype=np.uint32)
    data = write_glb([("wall", {"category": "added", "part": "after"}, verts, faces)])
    parsed, binary = _chunks(data)
    nodes = parsed["nodes"]
    assert isinstance(nodes, list)
    node = nodes[0]
    assert isinstance(node, dict)
    assert node["name"] == "wall"
    extras = node["extras"]
    assert isinstance(extras, dict)
    assert extras["category"] == "added"
    assert extras["part"] == "after"
    views = parsed["bufferViews"]
    assert isinstance(views, list)
    first = views[0]
    assert isinstance(first, dict)
    start = int(first["byteOffset"])
    count = 9
    found = np.frombuffer(binary[start : start + count * 4], dtype=np.float32)
    assert np.allclose(found, verts.reshape(-1))
