"""Under egress none, a company or cloud send is never attempted."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from iterthink.services.bridge_real import RealBridge
from iterthink.services.egress import EgressDenied, deliver
from iterthink.services.projects import project_file, settings_of, write_yaml

_ROOT: Path | None = None


def _project() -> Path:
    global _ROOT
    if _ROOT is not None:
        return _ROOT
    tmp = Path(tempfile.mkdtemp())
    folder = tmp / "Notes"
    folder.mkdir()
    (folder / "note.md").write_text("hello\n", encoding="utf-8")
    RealBridge(state_dir=tmp / "state", machine="m-test").make_project(folder)
    data = settings_of(folder)
    data["egress"] = "none"
    write_yaml(project_file(folder), data)
    _ROOT = folder
    return folder


class _Router:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def send(self, text: str) -> str:
        self.calls.append(text)
        return text


@given(
    st.text(max_size=40),
    st.sampled_from(["agent", "app_ai", "chat", "impact", "mcp"]),
    st.sampled_from(["company", "cloud"]),
)
@settings(max_examples=20, deadline=None)
def test_egress_none_attempts_no_remote_call(text: str, purpose: str, tier: str) -> None:
    router = _Router()
    with pytest.raises(EgressDenied):
        deliver(_project(), purpose, tier, text, router.send)
    assert router.calls == []
