"""The desktop entry point, the Flet guard and the PyInstaller specs."""

from __future__ import annotations

import ast
import plistlib
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import iterthink

ROOT = Path(__file__).resolve().parents[3]
PACKAGING = ROOT / "packaging"
_SPECS = ("iterthink-linux.spec", "iterthink-windows.spec", "iterthink-macos.spec")

_BLOCK_FLET = textwrap.dedent(
    """
    import importlib.abc
    import sys

    class NoFlet(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name == "flet" or name.startswith("flet."):
                raise ImportError("flet is blocked")
            return None

    sys.meta_path.insert(0, NoFlet())
    import iterthink.__main__
    import iterthink.compare.engines
    import iterthink.desktop
    import iterthink.mcp.server
    import iterthink.services.bridge_real
    import iterthink.web.app
    assert not any(name == "flet" or name.startswith("flet.") for name in sys.modules)
    print("ok")
    """
)


def _python(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args], capture_output=True, text=True, cwd=ROOT, timeout=120, check=False
    )


def test_core_imports_without_flet() -> None:
    done = _python("-c", _BLOCK_FLET)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "ok"


def test_main_starts_desktop_and_version_prints(monkeypatch: pytest.MonkeyPatch) -> None:
    done = _python("-m", "iterthink", "--version")
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "iterthink 2.0.0a0"
    started: list[str] = []
    monkeypatch.setattr("iterthink.desktop.main", lambda: started.append("desktop"))
    monkeypatch.setattr("iterthink.web.__main__.main", lambda: started.append("browser"))
    monkeypatch.setattr("iterthink.mcp.server.main", lambda: started.append("mcp"))
    from iterthink.__main__ import cli

    cli([])
    cli(["--browser"])
    cli(["mcp"])
    assert started == ["desktop", "browser", "mcp"]


def _datas() -> list[tuple[str, str]]:
    sys.path.insert(0, str(PACKAGING))
    try:
        import build_common

        return [(str(source), str(target)) for source, target in build_common.datas()]
    finally:
        sys.path.remove(str(PACKAGING))
        sys.modules.pop("build_common", None)


def _called(spec: Path) -> set[str]:
    tree = ast.parse(spec.read_text(encoding="utf-8"))
    calls = (node for node in ast.walk(tree) if isinstance(node, ast.Call))
    return {call.func.id for call in calls if isinstance(call.func, ast.Name)}


def test_spec_includes_templates_static_defaults() -> None:
    package = Path(iterthink.__file__).parent
    datas = {Path(source).resolve(): target for source, target in _datas()}
    for rel in ("web/templates", "web/static", "defaults", "services/verify_log.py"):
        source = (package / rel).resolve()
        assert source in datas, rel
        assert source.exists(), rel
        expected = f"iterthink/{rel}" if source.is_dir() else f"iterthink/{Path(rel).parent}"
        assert datas[source] == expected
    assert (package / "web/static/vendor/three/build/three.module.js").is_file()
    for name in _SPECS:
        spec = PACKAGING / name
        assert {"Analysis", "EXE", "COLLECT"} <= _called(spec), name
        assert "build_common" in spec.read_text(encoding="utf-8"), name


def test_macos_plist_has_microphone_description() -> None:
    with (PACKAGING / "macos" / "Info.plist").open("rb") as handle:
        plist = plistlib.load(handle)
    assert plist["NSMicrophoneUsageDescription"].strip()
    assert plist["CFBundleIdentifier"]
    with (PACKAGING / "macos" / "entitlements.plist").open("rb") as handle:
        entitlements = plistlib.load(handle)
    assert entitlements["com.apple.security.device.audio-input"] is True
    assert "Info.plist" in (PACKAGING / "iterthink-macos.spec").read_text(encoding="utf-8")
