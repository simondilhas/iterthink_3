"""Model views on the real bridge: GLBs and progress of a model diff."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Protocol, cast

from iterthink.services.bridge import NotFound
from iterthink.services.projects import file_pair


class _Host(Protocol):
    def _root(self, project: str) -> Path: ...


class ModelsBridge:
    """Serves what a model diff wrote to the machine cache and its counters."""

    def model_glb(self, project: str, key: str, part: Literal["before", "after", "diff"]) -> bytes:
        from iterthink.compare.ifc_glb import cached

        cast(_Host, self)._root(project)
        found = cached(key, part)
        if found is None:
            raise NotFound(f"no {part} view for that model comparison")
        return found

    def diff_progress(
        self, project: str, path: str, base: str | None = None, target: str | None = None
    ) -> Mapping[str, int]:
        from iterthink.compare.ifc_progress import counters, key_of

        pair = file_pair(cast(_Host, self)._root(project), path, base, target)
        return {} if pair is None else counters(key_of(*pair))
