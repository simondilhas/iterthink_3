"""Static architecture checks. They read source code; they import nothing from iterthink.

If one fails, fix the code. Never add to allowlists.py (see its docstring).
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from functools import cache
from pathlib import Path

import pytest

from . import allowlists

REPO_ROOT = Path(__file__).resolve().parents[3]
PKG = REPO_ROOT / "iterthink"

CORE_PACKAGES = ("compare", "services", "persistence", "db", "contract", "ai")
UI_PACKAGES = ("web", "mcp", "desktop", "studio")
REMOTE_CLIENTS = ("httpx", "requests", "urllib.request", "aiohttp", "ollama", "openai", "anthropic")
FORBIDDEN_JJ_OPS = ("abandon", "squash", "gc", "undo")
UI_IMPORT_PREFIXES = (*(f"iterthink.{name}" for name in UI_PACKAGES), "flet", "fastapi", "jinja2")
UI_FORBIDDEN_WORDS = (
    "commit",
    "commits",
    "branch",
    "branches",
    "rebase",
    "bookmark",
    "repository",
    "checkout",
    "jj",
    "git",
)
SKIP_DIRS = {
    ".venv",
    "venv",
    ".git",
    ".jj",
    "node_modules",
    "build",
    "dist",
    ".pytest_cache",
    ".pytest_store",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
}


# --- helpers ----------------------------------------------------------------


def rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def package_files() -> list[Path]:
    if not PKG.is_dir():
        pytest.skip("iterthink/ package not found; run from the repo root")
    return sorted(p for p in PKG.rglob("*.py") if not SKIP_DIRS & set(p.parts))


@cache
def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imported_modules(path: Path) -> Iterator[str]:
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


def imports_any(path: Path, prefixes: tuple[str, ...]) -> list[str]:
    hits = []
    for mod in imported_modules(path):
        if any(mod == p or mod.startswith(p + ".") for p in prefixes):
            hits.append(mod)
    return hits


def allowed(path: Path, allowlist: dict[str, str]) -> bool:
    r = rel(path)
    return any(r == key or (key.endswith("/") and r.startswith(key)) for key in allowlist)


def core_files() -> list[Path]:
    return [p for p in package_files() if p.relative_to(PKG).parts[0] in CORE_PACKAGES]


def string_constants(path: Path) -> Iterator[tuple[int, str]]:
    """(line, value) for every string literal in the module."""
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def report(violations: list[str], rule: str) -> None:
    if violations:
        lines = "\n  ".join(violations)
        pytest.fail(f"{rule}\n  {lines}\nFix the code; allowlists only shrink.")


# --- rules ------------------------------------------------------------------


SURFACE_ALLOWED = ("iterthink.services.bridge", "iterthink.web", "iterthink.mcp")


def test_surfaces_reach_core_only_through_the_bridge() -> None:
    """web/, mcp/ and desktop.py import from iterthink only the bridge and themselves."""
    surfaces = [
        p
        for p in package_files()
        if p.relative_to(PKG).parts[0] in ("web", "mcp") or p.name == "desktop.py"
    ]
    bad = []
    for p in surfaces:
        for mod in imported_modules(p):
            internal = mod == "iterthink" or mod.startswith("iterthink.")
            permitted = any(mod == a or mod.startswith(a + ".") for a in SURFACE_ALLOWED)
            if internal and not permitted:
                bad.append(f"{rel(p)}: {mod}")
    report(bad, "surface imports core directly; go through services/bridge.py:")


def test_flet_only_in_legacy_ui() -> None:
    bad = [
        f"{rel(p)}: {', '.join(hits)}"
        for p in package_files()
        if (hits := imports_any(p, ("flet",))) and not allowed(p, allowlists.FLET_IMPORTS)
    ]
    report(bad, "flet imported outside the legacy UI:")


def test_core_does_not_import_ui() -> None:
    bad = [
        f"{rel(p)}: {', '.join(hits)}"
        for p in core_files()
        if (hits := imports_any(p, UI_IMPORT_PREFIXES))
        and not allowed(p, allowlists.CORE_IMPORTS_UI)
    ]
    report(bad, "core module imports UI code:")


def test_remote_clients_only_in_ai_and_egress() -> None:
    def permitted(p: Path) -> bool:
        r = p.relative_to(PKG)
        return r.parts[0] == "ai" or r.as_posix() == "services/egress.py"

    bad = [
        f"{rel(p)}: {', '.join(hits)}"
        for p in package_files()
        if not permitted(p)
        and (hits := imports_any(p, REMOTE_CLIENTS))
        and not allowed(p, allowlists.REMOTE_CLIENT_IMPORTS)
    ]
    report(bad, "remote client imported outside ai/ and services/egress.py:")


def test_only_vcs_module_runs_jj() -> None:
    vcs = PKG / "persistence" / "vcs.py"
    bad = [
        f"{rel(p)}:{line}"
        for p in package_files()
        if p != vcs
        for line, value in string_constants(p)
        if value == "jj"
    ]
    report(bad, "the string 'jj' (a jj invocation) outside persistence/vcs.py:")


def test_vcs_uses_forbidden_ops_only_in_erase() -> None:
    vcs = PKG / "persistence" / "vcs.py"
    if not vcs.exists():
        pytest.skip("persistence/vcs.py not written yet (S03)")
    bad: list[str] = []

    def visit(node: ast.AST, in_erase: bool) -> None:
        for child in ast.iter_child_nodes(node):
            erase = in_erase or (
                isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                and child.name.startswith("erase")
            )
            if isinstance(child, ast.Constant) and child.value in FORBIDDEN_JJ_OPS and not erase:
                bad.append(f"{rel(vcs)}:{child.lineno} '{child.value}'")
            visit(child, erase)

    visit(parse(vcs), False)
    report(bad, "forbidden jj operation outside an erase_* function:")


_MODE = re.compile(r"^[rwxabt+]{1,3}$")


def _append_mode(call: ast.Call) -> bool:
    """True for open(..., "a"), Path.open("a"), open(..., mode="a+") and similar."""
    func = call.func
    if isinstance(func, ast.Name):
        name = func.id
    elif isinstance(func, ast.Attribute):
        name = func.attr
    else:
        return False
    if name != "open":
        return False
    values = [a.value for a in call.args if isinstance(a, ast.Constant)]
    values += [
        k.value.value
        for k in call.keywords
        if k.arg == "mode" and isinstance(k.value, ast.Constant)
    ]
    return any(isinstance(v, str) and _MODE.match(v) and "a" in v for v in values)


def test_only_event_log_appends_to_files() -> None:
    log = PKG / "services" / "event_log.py"
    bad = [
        f"{rel(p)}:{n.lineno}"
        for p in package_files()
        if p != log and not allowed(p, allowlists.APPEND_MODE_WRITES)
        for n in ast.walk(parse(p))
        if isinstance(n, ast.Call) and _append_mode(n)
    ]
    report(bad, "file opened in append mode outside services/event_log.py:")


def test_no_gitignore_written_into_user_folders() -> None:
    bad = [
        f"{rel(p)}:{line}"
        for p in package_files()
        if not allowed(p, allowlists.GITIGNORE_REFS)
        for line, value in string_constants(p)
        if ".gitignore" in value
    ]
    report(bad, "'.gitignore' referenced in package code (D-006):")


def test_no_tamper_proof_wording() -> None:
    texts = package_files()
    web = PKG / "web"
    if web.is_dir():
        texts += [p for p in web.rglob("*") if p.suffix in {".html", ".js", ".css"}]
    bad = [
        rel(p) for p in texts if re.search(r"tamper[- ]?proof", p.read_text(encoding="utf-8"), re.I)
    ]
    report(bad, "'tamper-proof' wording; use 'tamper-evident' (D-005):")


def test_no_node_toolchain() -> None:
    markers = (
        "package.json",
        "package-lock.json",
        "tsconfig.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "vite.config.js",
        "webpack.config.js",
    )
    bad = [
        rel(p)
        for p in REPO_ROOT.rglob("*")
        if not SKIP_DIRS & set(p.relative_to(REPO_ROOT).parts)
        and (p.name in markers or p.suffix in {".ts", ".tsx"})
    ]
    report(bad, "Node/TypeScript toolchain files (D-001):")


def test_ui_text_has_no_vcs_vocabulary() -> None:
    templates = PKG / "web" / "templates"
    if not templates.is_dir():
        pytest.skip("web/templates not written yet (S07)")
    word = re.compile(r"\b(" + "|".join(UI_FORBIDDEN_WORDS) + r")\b", re.I)
    tag_or_expr = re.compile(r"<[^>]*>|\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.S)
    bad = []
    for path in templates.rglob("*.html"):
        visible = tag_or_expr.sub(" ", path.read_text(encoding="utf-8"))
        for m in word.finditer(visible):
            bad.append(f"{rel(path)}: '{m.group(0)}'")
    report(bad, "Git/jj words in UI text; use version, change, proposal, accept, reject, restore:")


def test_default_seeds_are_valid_yaml() -> None:
    yaml = pytest.importorskip("yaml")
    defaults = PKG / "defaults"
    if not defaults.is_dir():
        pytest.skip("no defaults/")
    bad = []
    for path in sorted(defaults.rglob("*.y*ml")):
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            bad.append(f"{rel(path)}: {exc}")
    report(bad, "invalid YAML in seed files:")


@pytest.mark.parametrize(
    "name",
    [
        "FLET_IMPORTS",
        "CORE_IMPORTS_UI",
        "REMOTE_CLIENT_IMPORTS",
        "APPEND_MODE_WRITES",
        "GITIGNORE_REFS",
    ],
)
def test_allowlist_entries_are_still_needed(name: str) -> None:
    """A fixed violation must leave the allowlist, so the list keeps shrinking."""
    checks = {
        "FLET_IMPORTS": lambda p: bool(imports_any(p, ("flet",))),
        "CORE_IMPORTS_UI": lambda p: bool(imports_any(p, UI_IMPORT_PREFIXES)),
        "REMOTE_CLIENT_IMPORTS": lambda p: bool(imports_any(p, REMOTE_CLIENTS)),
        "APPEND_MODE_WRITES": lambda p: any(
            isinstance(n, ast.Call) and _append_mode(n) for n in ast.walk(parse(p))
        ),
        "GITIGNORE_REFS": lambda p: any(".gitignore" in v for _, v in string_constants(p)),
    }
    entries: dict[str, str] = getattr(allowlists, name)
    files = package_files()
    stale = []
    for key in entries:
        covered = [p for p in files if allowed(p, {key: ""})]
        if not any(checks[name](p) for p in covered):
            stale.append(key)
    report(stale, f"{name}: entries no longer needed, remove them:")
