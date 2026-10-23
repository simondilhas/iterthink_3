"""Property-based invariants over random sequences of bridge actions (fake and real)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from iterthink.services.bridge import Conflict

from .conftest import _make

ACTIONS = st.lists(
    st.tuples(
        st.sampled_from(["save", "propose", "accept", "reject"]),
        st.sampled_from(["a.md", "b.md"]),
        st.text(alphabet="xyz ", min_size=1, max_size=8),
    ),
    min_size=1,
    max_size=12,
)


@settings(
    max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None
)
@given(actions=ACTIONS)
def test_files_change_only_through_save_or_accept(
    impl: str, actions: list[tuple[str, str, str]]
) -> None:
    """Invariants 3 and 4: the disk always equals the model built from saves and
    accepted proposals; proposals and rejects never touch files."""
    tmp = Path(tempfile.mkdtemp())
    try:
        project = tmp / "P"
        project.mkdir()
        (project / "a.md").write_text("start a\n", encoding="utf-8")
        (project / "b.md").write_text("start b\n", encoding="utf-8")
        bridge = _make(impl, tmp / "state")
        pid = bridge.make_project(project).id
        model = {"a.md": "start a\n", "b.md": "start b\n"}
        open_props: list[tuple[str, str, str, str]] = []  # id, path, text, base

        for action, path, text in actions:
            if action == "save":
                bridge.save(pid, path, text, "user:t")
                model[path] = text
            elif action == "propose":
                prop = bridge.propose(pid, {path: text}, "agent:t", "r")
                open_props.append((prop.id, path, text, model[path]))
            elif open_props:
                prop_id, ppath, ptext, base = open_props.pop(0)
                if action == "reject":
                    bridge.reject(pid, prop_id, "user:t", "nein")
                elif model[ppath] != base:
                    with pytest.raises(Conflict):
                        bridge.accept(pid, prop_id, "user:t")
                else:
                    bridge.accept(pid, prop_id, "user:t")
                    model[ppath] = ptext
            disk = {p: (project / p).read_text(encoding="utf-8") for p in model}
            assert disk == model
        assert bridge.verify(pid).ok
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
