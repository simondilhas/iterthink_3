"""Fixtures and guards for all iterthink 2.0 tests.

Markers: integration, jj, slow, e2e, network (see .cursor/rules/10-testing.mdc).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import socket
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "iterthink"

_MARKERS = {
    "integration": "real files, real SQLite, several modules",
    "jj": "needs the jj binary (jj_bin fixture)",
    "slow": "takes more than 1 s; only in --full",
    "e2e": "full user flow through the FastAPI TestClient",
    "network": "may open non-loopback sockets",
}

try:  # Hypothesis profiles: HYPOTHESIS_PROFILE=ci for more examples
    from hypothesis import HealthCheck, settings

    settings.register_profile("dev", max_examples=50, deadline=None)
    settings.register_profile(
        "ci",
        max_examples=300,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
except ImportError:  # pragma: no cover - hypothesis is a dev dependency
    pass


def pytest_configure(config: pytest.Config) -> None:
    for name, help_text in _MARKERS.items():
        config.addinivalue_line("markers", f"{name}: {help_text}")


# --- network guard ---------------------------------------------------------

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _host_of(address: object) -> str | None:
    if isinstance(address, tuple) and address:
        return str(address[0])
    return None  # unix sockets etc.


@pytest.fixture(autouse=True)
def _no_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that opens a non-loopback socket unless marked `network`."""
    if request.node.get_closest_marker("network"):
        return
    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: object) -> None:
        host = _host_of(address)
        if host is not None and host not in _LOOPBACK:
            raise RuntimeError(
                f"Test tried to reach {host}. Tests run offline; use a fake "
                "or mark the test @pytest.mark.network."
            )
        real_connect(self, address)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


# --- jj --------------------------------------------------------------------


@pytest.fixture
def jj_bin() -> str:
    """Path to jj. Skips locally if missing; fails when ITERTHINK_REQUIRE_JJ=1."""
    path = os.environ.get("ITERTHINK_JJ") or shutil.which("jj")
    if path:
        return path
    if os.environ.get("ITERTHINK_REQUIRE_JJ") == "1":
        pytest.fail("jj is required (ITERTHINK_REQUIRE_JJ=1) but not on PATH")
    pytest.skip("jj not installed")


# --- projects --------------------------------------------------------------

SourceSnapshot = dict[str, str]


def _is_iterthink_data(rel: Path) -> bool:
    return bool(rel.parts) and rel.parts[0] in {".iterthink", ".jj"}


def snapshot_sources(project: Path) -> SourceSnapshot:
    """sha256 of every user source file (excludes .iterthink/ and .jj/)."""
    result: SourceSnapshot = {}
    for path in sorted(project.rglob("*")):
        rel = path.relative_to(project)
        if path.is_file() and not _is_iterthink_data(rel):
            result[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


@pytest.fixture
def source_snapshot() -> Callable[[Path], SourceSnapshot]:
    """Call before and after an action; assert equal unless a proposal was accepted."""
    return snapshot_sources


@pytest.fixture
def workspace_dir(tmp_path: Path) -> Path:
    ws = tmp_path / "Arbeitsbereich"
    ws.mkdir()
    return ws


@pytest.fixture
def project_dir(workspace_dir: Path) -> Path:
    """A project with Markdown, CSV, a subfolder and a non-ASCII path."""
    project = workspace_dir / "P-101 Schulhaus"
    (project / "Pläne").mkdir(parents=True)
    (project / "Pflichtenheft.md").write_text(
        "# Pflichtenheft\n\nDie Türen im EG sind EI30.\n\nFluchtwege 1.2 m.\n",
        encoding="utf-8",
    )
    (project / "Türliste.csv").write_text(
        "id,geschoss,typ,brandschutz\nT01,EG,Holz,EI30\nT02,EG,Glas,\n",
        encoding="utf-8",
    )
    (project / "Pläne" / "Notiz Grundriss EG.md").write_text("Stand 1\n", encoding="utf-8")
    return project


@pytest.fixture
def second_project_dir(workspace_dir: Path) -> Path:
    """A second project in the same workspace, for isolation tests."""
    project = workspace_dir / "P-102 Turnhalle"
    project.mkdir()
    (project / "Notizen.md").write_text("# Turnhalle\n", encoding="utf-8")
    return project


# --- time ------------------------------------------------------------------


class FixedClock:
    """Deterministic clock: each call advances by `step`."""

    def __init__(self, start: datetime, step: timedelta) -> None:
        self._now = start
        self._step = step

    def __call__(self) -> datetime:
        current = self._now
        self._now += self._step
        return current


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock(datetime(2026, 10, 23, 5, 0, tzinfo=UTC), timedelta(seconds=1))
