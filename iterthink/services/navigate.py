"""The model picks a place to open from a list it is given. It never makes one up."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from iterthink.services.bridge import FileEntry, ProjectInfo
from iterthink.services.projects import folder_entries

PROMPT_ID = "navigate-v1"
_FILES = 300
_QUOTES = "`'\""
_SCORE_TAIL = re.compile(r"\s+(?:0(?:\.\d+)?|1(?:\.0+)?)$")
_OTHER_WORDS = "The line may describe a place in other words or in another language. "
_IN_PROJECT = (
    "If the line asks to open, show, go to or switch to one of the places below, "
    "reply with open and the place copied exactly, for example: open {example}. "
    + _OTHER_WORDS
    + "Otherwise answer as above.\nPlaces:\n"
)
_ON_START = (
    "The line names a place to open. Reply with open and one place copied exactly "
    "from the list, for example: open {example}. "
    + _OTHER_WORDS
    + "Reply none if it names none of them.\nPlaces:\n"
)


@dataclass(frozen=True)
class Place:
    kind: Literal["file", "project", "folder"]
    target: str  # file path in the project, project id, or absolute folder path


Places = dict[str, Place]


def project_places(
    files: Iterable[FileEntry], projects: Iterable[ProjectInfo], current: str
) -> Places:
    """Other projects, then the files of the current one."""
    found: Places = {}
    for info in projects:
        if info.id != current:
            found.setdefault(f"project: {info.name}", Place("project", info.id))
    for count, entry in enumerate(files):
        if count >= _FILES:
            break
        found[f"file: {entry.path}"] = Place("file", entry.path)
    return found


class _Lister(Protocol):
    def files(self, project: str) -> list[FileEntry]: ...
    def projects(self) -> list[ProjectInfo]: ...


def of_project(host: _Lister | None, project: str) -> Places:
    if host is None or not project:
        return {}
    return project_places(host.files(project), host.projects(), project)


def start_places(
    projects: Iterable[ProjectInfo], folders: Iterable[tuple[Path, str | None]]
) -> Places:
    """Projects, then workspace folders that are not projects yet."""
    found: Places = {}
    for info in projects:
        found.setdefault(f"project: {info.name}", Place("project", info.id))
    for folder, project in folders:
        if project is None:
            found.setdefault(f"folder: {folder.name}", Place("folder", str(folder)))
    return found


def in_project_prompt(base: str, places: Places) -> str:
    if not places:
        return base
    head = _IN_PROJECT.format(example=next(iter(places)))
    return f"{base}\n\n{head}" + "\n".join(places)


def start_prompt(places: Places) -> str:
    return _ON_START.format(example=next(iter(places))) + "\n".join(places)


def targets(place: Place) -> tuple[str | None, str | None]:
    """A file to reopen in this project, or a page to go to."""
    if place.kind == "file":
        return place.target, None
    if place.kind == "project":
        return None, f"/p/{place.target}"
    return None, None


def on_start(
    complete: Callable[[str, str, str], str],
    projects: Iterable[ProjectInfo],
    workspace: Path,
    line: str,
) -> tuple[Literal["project", "folder"], str] | None:
    """The project page or workspace folder the start-screen line names."""
    places = start_places(projects, folder_entries(workspace))
    if not places:
        return None
    place = chosen(complete(start_prompt(places), line, "local"), places)
    if place is None or place.kind == "file":
        return None
    if place.kind == "project":
        return "project", f"/p/{place.target}"
    return "folder", place.target


def chosen(reply: str, places: Places) -> Place | None:
    """The place an `open …` reply names, matched against the list. Anything else is None."""
    lines = reply.strip().splitlines()
    if not lines:
        return None
    text = lines[0].strip().strip(_QUOTES + ".").strip()
    head, _, rest = text.partition(" ")
    if head.rstrip(":").casefold() != "open":
        return None
    raw = rest.strip().strip(_QUOTES).casefold()
    for wanted in (raw, _SCORE_TAIL.sub("", raw).strip(_QUOTES)):
        bare = wanted.partition(": ")[2]
        for label, place in places.items():
            name = label.partition(": ")[2].casefold()
            if wanted in (label.casefold(), name) or bare == name:
                return place
    return None
