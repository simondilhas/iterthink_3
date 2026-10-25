"""Task context for the app builder. Paths and schemas, never file contents."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Protocol

from iterthink.services.app_validate import bridge_reference, component_reference
from iterthink.services.bridge import FileContent, FileEntry
from iterthink.services.egress import prepare
from iterthink.services.projects import read_yaml
from iterthink.services.settings import get

_SEED = Path(__file__).resolve().parents[1] / "defaults" / "app_builder.md"
_EXAMPLES = Path(__file__).resolve().parents[1] / "defaults" / "app_examples"
_TIERS = {"local", "company", "cloud"}
_WORDS = re.compile(r"[a-z0-9]+")


class _Files(Protocol):
    def _root(self, project: str) -> Path: ...
    def files(self, project: str) -> list[FileEntry]: ...
    def read(self, project: str, path: str) -> FileContent: ...


def prompt_version() -> str:
    """Short id of the builder seed. It changes when the seed changes."""
    return hashlib.sha256(_SEED.read_bytes()).hexdigest()[:12]


def tier_of(root: Path) -> str:
    """`apps.builder_tier`, or local when the stored value is not a tier."""
    raw = get(root, "apps.builder_tier").value
    if isinstance(raw, str) and raw in _TIERS:
        return raw
    return "local"


def system_prompt() -> str:
    """Rules, generated references, and the shipped examples."""
    parts = [
        _SEED.read_text(encoding="utf-8").rstrip(),
        bridge_reference(),
        component_reference(),
        _example_text(),
    ]
    return "\n\n".join(part for part in parts if part)


def user_prompt(host: _Files, project: str, line: str, tier: str) -> str:
    """The line, the file list and schemas. Remote tiers are shielded first."""
    root = host._root(project)
    body = "\n\n".join(
        (
            f"Line:\n{line}",
            f"Files:\n{_file_list(host, project)}",
            f"Schemas:\n{_schemas(host, project)}",
            f"Kept apps:\n{_kept(root, line)}",
        )
    )
    if tier == "company":
        return prepare(root, body, "app_build", "company").text
    if tier == "cloud":
        return prepare(root, body, "app_build", "cloud").text
    return body


def _file_list(host: _Files, project: str) -> str:
    rows = [f"{item.path} {item.kind} {item.size}" for item in host.files(project)]
    return "\n".join(rows)


def _schemas(host: _Files, project: str) -> str:
    rows: list[str] = []
    for item in host.files(project):
        content = host.read(project, item.path)
        schema = _one_schema(item.path, item.kind, content.text)
        if schema:
            rows.append(schema)
    return "\n".join(rows)


def _one_schema(path: str, kind: str, text: str | None) -> str:
    if not text:
        return ""
    if kind == "table":
        header = text.splitlines()[0] if text.splitlines() else ""
        return f"{path} columns: {header}"
    if kind != "markdown":
        return ""
    headings = [line for line in text.splitlines() if line.startswith("#")]
    if not headings:
        return ""
    return path + "\n" + "\n".join(headings)


def _kept(root: Path, line: str) -> str:
    folder = root / ".iterthink" / "apps"
    if not folder.is_dir():
        return ""
    words = _words(line)
    found: list[str] = []
    for child in sorted(folder.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        data = read_yaml(child / "manifest.yaml")
        purpose = data.get("purpose")
        status = data.get("status")
        if status != "kept" or not isinstance(purpose, str) or not (words & _words(purpose)):
            continue
        found.append(purpose)
        if len(found) == 3:
            break
    return "\n".join(found)


def _words(text: str) -> set[str]:
    return {word for word in _WORDS.findall(text.casefold()) if len(word) > 2}


def _example_text() -> str:
    if not _EXAMPLES.is_dir():
        return ""
    chunks: list[str] = []
    for path in sorted(_EXAMPLES.glob("*/index.html")):
        chunks.append(f"Example {path.parent.name}:\n{path.read_text(encoding='utf-8').strip()}")
    return "\n\n".join(chunks)
