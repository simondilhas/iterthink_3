"""Static checks and the generated bridge reference for ad-hoc apps."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ALLOWED = frozenset({"listFiles", "readFile", "history", "search", "compare", "propose"})
LIMIT = 200_000
_FACING = {
    "files": "listFiles",
    "read": "readFile",
    "history": "history",
    "search": "search",
    "diff": "compare",
    "propose": "propose",
}
_SKIP = {"self", "project", "actor"}
_BANNED = (
    ("fetch(", "fetch"),
    ("XMLHttpRequest", "XMLHttpRequest"),
    ("WebSocket", "WebSocket"),
    ("eval(", "eval"),
    ("new Function", "new Function"),
)
_CALL = re.compile(r"bridge\.([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)")
_REF = re.compile(
    r"""<(?:script|link)\b[^>]*?\s(?:src|href)\s*=\s*(['"]?)([^'">\s]+)\1""",
    re.IGNORECASE,
)
_IMPORT = re.compile(r"""import\s*\(\s*(['"])([^'"]+)\1""")
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_BRIDGE = Path(__file__).resolve().parent / "bridge.py"
_COMPONENTS = Path(__file__).resolve().parents[1] / "web" / "static" / "js" / "components.json"


def bridge_calls(source: str) -> list[tuple[str, str]]:
    """`(name, raw args)` for every `bridge.name(...)` call."""
    return _CALL.findall(source)


def bridge_reference() -> str:
    """App-facing names generated from `services/bridge.py`."""
    lines = ["App bridge names (the parent adds the project and the actor):"]
    for facing, item in _methods():
        args = [arg.arg for arg in item.args.args if arg.arg not in _SKIP]
        first = (ast.get_docstring(item) or "").split("\n", 1)[0].strip()
        lines.append(f"- {facing}({', '.join(args)}) {first}".rstrip())
    return "\n".join(lines)


def component_reference() -> str:
    """Custom elements from `static/js/components.json`."""
    loaded = json.loads(_COMPONENTS.read_text(encoding="utf-8"))
    lines = ["Components:"]
    if isinstance(loaded, dict):
        for name, spec in loaded.items():
            example = spec.get("example") if isinstance(spec, dict) else ""
            shown = example if isinstance(example, str) else ""
            lines.append(f"- {name} {shown}".rstrip())
    return "\n".join(lines)


def parse_build(text: str) -> dict[str, object] | None:
    """The builder JSON, or None when the contract is missing."""
    try:
        loaded = json.loads(_FENCE.sub("", text).strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    for key in ("slug", "title", "purpose", "html"):
        if not isinstance(loaded.get(key), str) or not str(loaded.get(key)).strip():
            return None
    inputs = loaded.get("inputs", [])
    if not isinstance(inputs, list):
        return None
    return loaded


def problems(html: str, module: str = "") -> list[str]:
    """Reasons the HTML or module must not be shown."""
    source = f"{html}\n{module}"
    errors = [f"{label} is not allowed" for needle, label in _BANNED if needle in source]
    errors.extend(_remote_refs(source))
    errors.extend(_remote_imports(source))
    for name, _raw in bridge_calls(source):
        if name not in ALLOWED:
            errors.append(f"{name} is not an allowlisted bridge")
    if len(source.encode("utf-8")) > LIMIT:
        errors.append("the app is larger than 200 KB")
    return errors


def _methods() -> list[tuple[str, ast.FunctionDef]]:
    tree = ast.parse(_BRIDGE.read_text(encoding="utf-8"))
    found: list[tuple[str, ast.FunctionDef]] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "Bridge":
            continue
        for item in node.body:
            facing = _FACING.get(item.name) if isinstance(item, ast.FunctionDef) else None
            if isinstance(item, ast.FunctionDef) and facing is not None:
                found.append((facing, item))
    return found


def _remote_refs(source: str) -> list[str]:
    errors: list[str] = []
    for _quote, url in _REF.findall(source):
        if not url.startswith("/static/vendor/"):
            errors.append(f"{url} is outside /static/vendor/")
    return errors


def _remote_imports(source: str) -> list[str]:
    errors: list[str] = []
    for _quote, url in _IMPORT.findall(source):
        if url.startswith(("http://", "https://", "//")):
            errors.append(f"{url} is a remote import")
    return errors
