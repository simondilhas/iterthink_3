"""Runs every contract test against each bridge implementation.

- fake: always.
- real: once `iterthink/services/bridge_real.py` exists (slice B1); needs jj.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from iterthink.services.bridge import Bridge

HAS_REAL = importlib.util.find_spec("iterthink.services.bridge_real") is not None


def _make(kind: str, state_dir: Path) -> Bridge:
    if kind == "fake":
        from iterthink.services.bridge_fake import FakeBridge

        return FakeBridge()
    from iterthink.services.bridge_real import RealBridge  # type: ignore[import-not-found,unused-ignore]

    bridge: Bridge = RealBridge(state_dir=state_dir, machine="m-test")
    return bridge


IMPLEMENTATIONS = [
    pytest.param("fake", id="fake"),
    pytest.param(
        "real",
        id="real",
        marks=[
            pytest.mark.jj,
            pytest.mark.skipif(not HAS_REAL, reason="bridge_real not written yet (B1)"),
        ],
    ),
]


@dataclass
class Ctx:
    bridge: Bridge
    project: str
    root: Path
    actor: str = "user:simon"


@pytest.fixture(params=IMPLEMENTATIONS)
def impl(request: pytest.FixtureRequest) -> str:
    kind: str = request.param
    if kind == "real":
        request.getfixturevalue("jj_bin")
    return kind


@pytest.fixture
def make_bridge(impl: str, tmp_path: Path) -> Callable[[], Bridge]:
    def factory() -> Bridge:
        return _make(impl, tmp_path / "machine-state")

    return factory


@pytest.fixture
def ctx(make_bridge: Callable[[], Bridge], project_dir: Path) -> Ctx:
    bridge = make_bridge()
    info = bridge.make_project(project_dir)
    return Ctx(bridge=bridge, project=info.id, root=project_dir)
