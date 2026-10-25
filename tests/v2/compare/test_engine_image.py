"""Image changes are regions on a scaled picture."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

from iterthink.compare.engines import diff


def _png(size: tuple[int, int], boxes: list[tuple[tuple[int, int, int, int], str]]) -> bytes:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for box, color in boxes:
        draw.rectangle(box, fill=color)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_identical_images_are_none() -> None:
    picture = _png((8, 8), [])
    result = diff("photo.png", picture, picture)
    assert result.kind == "none"
    assert result.summary == "no changes"


def test_changed_region_has_normalised_bbox() -> None:
    before = _png((10, 10), [])
    after = _png((10, 10), [((8, 8, 9, 9), "black")])
    result = diff("photo.png", before, after)
    assert result.summary == "1 area changed"
    regions = result.details["regions"]
    assert isinstance(regions, list)
    assert len(regions) == 1
    box = regions[0]
    assert isinstance(box, list)
    assert len(box) == 4
    assert all(isinstance(value, float) and 0.0 <= value <= 1.0 for value in box)
    assert box[0] >= 0.7
    assert box[1] >= 0.7


def test_different_sizes_are_compared_scaled() -> None:
    before = _png((10, 10), [])
    after = _png((20, 20), [((16, 16, 19, 19), "black")])
    result = diff("render.jpg", before, after)
    assert result.summary == "1 area changed"
    regions = result.details["regions"]
    assert isinstance(regions, list)
    box = regions[0]
    assert isinstance(box, list)
    assert box[0] >= 0.7
    assert box[1] >= 0.7
