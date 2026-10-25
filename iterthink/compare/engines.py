"""Format engines. ``diff`` picks one from the file kind."""

from __future__ import annotations

from typing import Protocol

from iterthink.compare.engine_ifc import IfcEngine
from iterthink.compare.engine_image import ImageEngine
from iterthink.compare.engine_plan import PlanEngine
from iterthink.compare.engine_table import TableEngine
from iterthink.compare.engine_text import TextEngine
from iterthink.services.bridge import FileDiff, FileKind, kind_of


class FormatEngine(Protocol):
    """One format. ``kinds`` are the file kinds it knows."""

    kinds: tuple[FileKind, ...]

    def diff(self, path: str, before: bytes | None, after: bytes | None) -> FileDiff:
        """Diff ``before`` and ``after`` for ``path``."""


_ENGINES: list[FormatEngine] = []


def register(engine: FormatEngine) -> None:
    """Add an engine. The first registered engine whose kinds match is used."""
    _ENGINES.append(engine)


def diff(path: str, before: bytes | None, after: bytes | None) -> FileDiff:
    """Diff two states of ``path``. Identical bytes are not a change."""
    if before == after:
        return FileDiff(path, "none", "no changes")
    kind = kind_of(path)
    for engine in _ENGINES:
        if kind in engine.kinds:
            return engine.diff(path, before, after)
    return FileDiff(path, "binary", "file changed")


register(TextEngine())
register(TableEngine())
register(PlanEngine())
register(IfcEngine())
register(ImageEngine())
