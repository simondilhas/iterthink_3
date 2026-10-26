"""Pixel diff for a photo or a rendering. Regions are advice, not a verdict."""

from __future__ import annotations

import base64
import io
from collections import deque

from PIL import Image, UnidentifiedImageError

from iterthink.services.bridge import FileDiff, FileKind

THRESHOLD = 24
_MEDIA = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".png": "image/png",
}


def _media(path: str) -> str:
    dot = path.rfind(".")
    suffix = path[dot:].lower() if dot >= 0 else ""
    return _MEDIA.get(suffix, "image/png")


def _channels(pixel: float | tuple[int, ...] | None) -> tuple[int, ...]:
    if isinstance(pixel, tuple):
        return tuple(int(channel) for channel in pixel)
    if isinstance(pixel, (int, float)):
        return (int(pixel),)
    return (0,)


def _differs(left: float | tuple[int, ...] | None, right: float | tuple[int, ...] | None) -> bool:
    pairs = zip(_channels(left), _channels(right), strict=False)
    return any(abs(a - b) > THRESHOLD for a, b in pairs)


def _details(
    path: str, regions: list[list[float]], before: bytes | None, after: bytes | None
) -> dict[str, object]:
    return {
        "regions": regions,
        "media": _media(path),
        "before_png": base64.b64encode(before).decode("ascii") if before else "",
        "after_png": base64.b64encode(after).decode("ascii") if after else "",
    }


def _box(minx: int, miny: int, maxx: int, maxy: int, width: int, height: int) -> list[float]:
    return [
        minx / width,
        miny / height,
        (maxx - minx + 1) / width,
        (maxy - miny + 1) / height,
    ]


def _fill(
    seen: list[list[bool]],
    before: Image.Image,
    after: Image.Image,
    start: tuple[int, int],
    width: int,
    height: int,
) -> list[float]:
    stack: deque[tuple[int, int]] = deque([start])
    seen[start[1]][start[0]] = True
    minx = maxx = start[0]
    miny = maxy = start[1]
    while stack:
        cx, cy = stack.pop()
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if nx < 0 or ny < 0 or nx >= width or ny >= height or seen[ny][nx]:
                continue
            seen[ny][nx] = True
            if not _differs(before.getpixel((nx, ny)), after.getpixel((nx, ny))):
                continue
            stack.append((nx, ny))
            minx, maxx = min(minx, nx), max(maxx, nx)
            miny, maxy = min(miny, ny), max(maxy, ny)
    return _box(minx, miny, maxx, maxy, width, height)


def _regions(before: bytes, after: bytes) -> list[list[float]]:
    earlier = Image.open(io.BytesIO(before)).convert("RGB")
    later = Image.open(io.BytesIO(after)).convert("RGB")
    width, height = later.size
    if earlier.size != later.size:
        earlier = earlier.resize((width, height))
    seen = [[False] * width for _ in range(height)]
    boxes: list[list[float]] = []
    for y in range(height):
        for x in range(width):
            if seen[y][x]:
                continue
            if not _differs(earlier.getpixel((x, y)), later.getpixel((x, y))):
                seen[y][x] = True
                continue
            boxes.append(_fill(seen, earlier, later, (x, y), width, height))
    return boxes


def _summary(count: int) -> str:
    noun = "area" if count == 1 else "areas"
    return f"{count} {noun} changed"


class ImageEngine:
    """Changed pixels, grouped, as boxes from 0 to 1."""

    kinds: tuple[FileKind, ...] = ("image",)

    def diff(self, path: str, before: bytes | None, after: bytes | None) -> FileDiff:
        if before is None or after is None:
            word = "image added" if before is None else "image removed"
            return FileDiff(path, "binary", word, details=_details(path, [], before, after))
        try:
            regions = _regions(before, after)
        except (OSError, UnidentifiedImageError, ValueError):
            return FileDiff(path, "binary", "file changed")
        if not regions:
            return FileDiff(path, "none", "no changes", details=_details(path, [], before, after))
        summary = _summary(len(regions))
        return FileDiff(path, "binary", summary, details=_details(path, regions, before, after))
