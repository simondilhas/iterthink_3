"""ATX heading parse. Pulled out of the 1.x sidebar so core does not import Flet."""

from __future__ import annotations

import re
from dataclasses import dataclass

_ATX_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_OPEN = re.compile(r"^\s*```")


@dataclass(frozen=True)
class ContentHeading:
    level: int
    title: str
    offset: int


def _strip_closing_hashes(title: str) -> str:
    t = title.rstrip()
    if " #" in t or t.endswith("#"):
        t = re.sub(r"\s+#+\s*$", "", t)
    return t.strip()


def parse_markdown_headings(text: str) -> list[ContentHeading]:
    """Return ATX headings (# … ######) with buffer offsets; skip fenced code blocks."""
    out: list[ContentHeading] = []
    in_fence = False
    offset = 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        stripped = body.strip()
        if _FENCE_OPEN.match(stripped):
            in_fence = not in_fence
            offset += len(line)
            continue
        if not in_fence:
            m = _ATX_HEADING.match(body)
            if m:
                level = len(m.group(1))
                title = _strip_closing_hashes(m.group(2))
                if title:
                    out.append(ContentHeading(level=level, title=title, offset=offset))
        offset += len(line)
    return out
