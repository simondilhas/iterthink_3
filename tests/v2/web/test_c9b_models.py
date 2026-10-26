"""The 3D view beside the model table."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

try:
    import ifcopenshell  # noqa: F401
except ImportError:
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        pytest.fail("ifcopenshell is required in CI")
    pytest.skip("ifcopenshell extra is not installed", allow_module_level=True)

from iterthink.persistence.snapshots import Snapshots
from iterthink.services.bridge_fake import FakeBridge
from iterthink.services.bridge_real import RealBridge
from iterthink.services.projects import tracked_files
from iterthink.web.app import TOKEN_HEADER, create_app

from ..fixtures.ifc_build import Item, build, guid_for

_HEADERS = {TOKEN_HEADER: "token"}
_CATEGORIES = ("added", "removed", "reshaped", "moved", "props_only", "unchanged")


def _version(project_dir: Path, data: bytes, message: str) -> str:
    (project_dir / "model.ifc").write_bytes(data)
    version = Snapshots(project_dir).snapshot(tracked_files(project_dir), message, "user:ada")
    assert version is not None
    return version.id


def _compare_page(
    tmp_path: Path, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, str]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    base = _version(project_dir, build([Item("wall", length=1), Item("door")]), "first")
    target = _version(project_dir, build([Item("wall", length=2)]), "second")
    client = TestClient(create_app(bridge=bridge, token="token", actor="user:ada"))
    page = client.get(
        f"/p/{project}/models/compare",
        params={"path": "model.ifc", "from": base, "to": target},
        headers=_HEADERS,
    )
    assert page.status_code == 200
    return client, page.text


def _attribute(html: str, name: str) -> str:
    found = re.search(rf'<ifc-diff[^>]*\s{name}="([^"]*)"', html)
    assert found, name
    return found.group(1).replace("&amp;", "&")


def test_model_compare_page_loads_viewer_and_legend(
    tmp_path: Path, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, html = _compare_page(tmp_path, project_dir, monkeypatch)
    assert '<script type="module" src="/static/js/ifc-viewer.js"' in html
    urls = {name: _attribute(html, name) for name in ("model-before", "model-after", "model-diff")}
    for url in urls.values():
        glb = client.get(url, headers=_HEADERS)
        assert glb.status_code == 200
        assert glb.content[:4] == b"glTF"
        assert glb.headers["content-type"] == "model/gltf-binary"
    changes = client.get(_attribute(html, "changes"), headers=_HEADERS).json()
    assert {row["guid"]: row["category"] for row in changes} == {
        guid_for("wall"): "reshaped",
        guid_for("door"): "removed",
    }
    legend = re.findall(r'<input type="checkbox" name="show" value="([a-z_]+)"', html)
    assert legend == list(_CATEGORIES)
    assert list((tmp_path / "config").rglob("*.glb"))
    assert not list(project_dir.rglob("*.glb"))
    assert '"three": "/static/vendor/three/build/three.module.js"' in html
    assert '"three/addons/": "/static/vendor/three/examples/jsm/"' in html


def test_viewer_script_works_offline() -> None:
    client = TestClient(create_app(bridge=FakeBridge(), token="token"))
    script = client.get("/static/js/ifc-viewer.js")
    assert script.status_code == 200
    assert 'customElements.define("ifc-diff"' in script.text
    assert 'customElements.define("ifc-viewer"' in script.text
    assert "http" not in re.sub(r"//.*", "", script.text)


def test_unknown_glb_is_not_found(
    tmp_path: Path, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    client = TestClient(create_app(bridge=bridge, token="token"))
    missing = client.get(f"/p/{project}/models/glb/{'0' * 64}/diff.glb", headers=_HEADERS)
    assert missing.status_code == 404
    odd = client.get(f"/p/{project}/models/glb/{'0' * 64}/model.glb", headers=_HEADERS)
    assert odd.status_code == 404


def _events(client: TestClient, url: str) -> str:
    text = ""
    with client.stream("GET", url, headers=_HEADERS) as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        for chunk in response.iter_text():
            text += chunk
            if "event: done" in text:
                break
    return text


@pytest.mark.slow
def test_large_model_reports_progress(
    tmp_path: Path, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("iterthink.web.routes.models._BACKGROUND_BYTES", 0)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    walls = [Item(f"wall{n}", x=2.0 * n) for n in range(30)]
    base = _version(project_dir, build(walls), "first")
    target = _version(project_dir, build([Item("wall0", length=2), *walls[1:]]), "second")
    client = TestClient(create_app(bridge=bridge, token="token"))
    query = {"path": "model.ifc", "from": base, "to": target}
    page = client.get(f"/p/{project}/models/compare", params=query, headers=_HEADERS)
    assert page.status_code == 200
    assert "<ifc-diff" not in page.text
    found = re.search(r'sse-connect="([^"]+)"', page.text)
    assert found
    stream = _events(client, found.group(1).replace("&amp;", "&"))
    assert "event: progress" in stream
    assert "30 of 30 elements matched" in stream
    assert "1 of 1 shape differences" in stream
    assert "event: table" in stream
    assert f'data-guid="{guid_for("wall0")}"' in stream
    assert "event: viewer" in stream
    assert "<ifc-diff" in stream
    progress = bridge.diff_progress(project, "model.ifc", base, target)
    assert progress["done"] == 1
    assert progress["matched"] == 30
