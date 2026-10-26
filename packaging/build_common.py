"""Shared PyInstaller settings for the per-platform spec files.

Build from the repository root, one folder per platform:

    uv sync --extra dev --extra ifc --extra voice --extra package
    uv run pyinstaller packaging/iterthink-<linux|windows|macos>.spec --noconfirm

Models (embeddings, speech) are not bundled; they download on first use.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "iterthink"
ENTRY = str(ROOT / "packaging" / "entry.py")
NAME = "iterthink"
EXCLUDES = ["flet", "tkinter", "pytest", "hypothesis", "mypy", "ruff", "IPython"]
_THIRD_PARTY = (
    "ifcopenshell",
    "webview",
    "sqlite_vec",
    "faster_whisper",
    "ctranslate2",
    "sounddevice",
    "fastembed",
    "rapidocr",
    "onnxruntime",
    "llama_cpp",
    "mcp",
    "daff",
    "spellchecker",
    "langdetect",
)


def datas() -> list[tuple[str, str]]:
    """iterthink's own files that are not Python modules."""
    own = [
        (PACKAGE / "web" / "templates", "iterthink/web/templates"),
        (PACKAGE / "web" / "static", "iterthink/web/static"),
        (PACKAGE / "defaults", "iterthink/defaults"),
        (PACKAGE / "services" / "verify_log.py", "iterthink/services"),
        (PACKAGE / "templates", "iterthink/templates"),
        (PACKAGE / "alembic", "iterthink/alembic"),
        (PACKAGE / "help.md", "iterthink"),
        (PACKAGE / "THIRD_PARTY_NOTICES.md", "iterthink"),
    ]
    return [(str(source), target) for source, target in own if source.exists()]


def collected() -> tuple[list[Any], list[Any], list[str]]:
    """Data, binaries and hidden imports that PyInstaller's analysis misses."""
    from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

    data: list[Any] = copy_metadata("iterthink")
    binaries: list[Any] = []
    hidden = collect_submodules("iterthink") + collect_submodules("uvicorn")
    for name in _THIRD_PARTY:
        try:
            more_data, more_binaries, more_hidden = collect_all(name)
        except Exception:  # noqa: S112 - an extra that is not installed is skipped
            continue
        data += more_data
        binaries += more_binaries
        hidden += more_hidden
    return data, binaries, hidden
