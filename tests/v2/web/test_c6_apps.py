"""The app page delivers a sandboxed frame. The shell CSP stays as it is."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from iterthink.services.bridge_real import RealBridge
from iterthink.web.app import TOKEN_HEADER, create_app

TOKEN = "test-token"
_HTML = "<main><h1>Doors</h1><script>bridge.readFile('Türliste.csv')</script></main>"


class _Model:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tier = "local"

    def complete(self, system: str, user: str, tier: str) -> str:
        assert system
        assert tier
        return self.text


def _page(tmp_path: Path, project_dir: Path) -> tuple[TestClient, str, str]:
    bridge = RealBridge(state_dir=tmp_path / "state", machine="m-test")
    project = bridge.make_project(project_dir).id
    bridge.use_app_model(
        _Model(
            json.dumps(
                {
                    "slug": "door-notes",
                    "title": "Door notes",
                    "purpose": "list doors",
                    "inputs": ["Türliste.csv"],
                    "html": _HTML,
                }
            )
        )
    )
    info = bridge.app_build(project, "list doors", "user:ada")
    app = create_app(bridge=bridge, token=TOKEN, actor="user:ada")
    client = TestClient(app, headers={TOKEN_HEADER: TOKEN, "accept": "text/html"})
    return client, project, info.id


def test_app_frame_uses_srcdoc_sandbox_without_same_origin(
    tmp_path: Path, project_dir: Path
) -> None:
    client, project, slug = _page(tmp_path, project_dir)
    page = client.get(f"/p/{project}/apps/{slug}")
    assert page.status_code == 200
    assert 'sandbox="allow-scripts"' in page.text
    assert "allow-same-origin" not in page.text
    assert "srcdoc=" in page.text
    assert "default-src &#39;none&#39;" in page.text or "default-src 'none'" in page.text
    assert "<iframe" in page.text
    assert "src=" not in page.text.split("<iframe", 1)[1].split(">", 1)[0].replace("srcdoc", "")


def test_app_reads_data_only_through_allowlisted_bridge(tmp_path: Path, project_dir: Path) -> None:
    client, project, slug = _page(tmp_path, project_dir)
    original = (project_dir / "Türliste.csv").read_text(encoding="utf-8")
    denied = client.post(
        f"/p/{project}/apps/{slug}/call",
        json={"name": "save", "args": {"path": "Türliste.csv", "text": "hacked"}},
    )
    assert denied.status_code == 200
    assert "propose" in denied.text
    assert (project_dir / "Türliste.csv").read_text(encoding="utf-8") == original
    allowed = client.post(
        f"/p/{project}/apps/{slug}/call",
        json={"name": "readFile", "args": {"path": "Türliste.csv"}},
    )
    assert "brandschutz" in allowed.text
    frame = Path("iterthink/web/static/js/app-bridge.js").read_text(encoding="utf-8")
    assert "fetch(" not in frame
    assert "XMLHttpRequest" not in frame


def test_shell_csp_unchanged_when_app_open(tmp_path: Path, project_dir: Path) -> None:
    client, project, slug = _page(tmp_path, project_dir)
    home = client.get(f"/p/{project}")
    opened = client.get(f"/p/{project}/apps/{slug}")
    assert home.headers.get("content-security-policy") == opened.headers.get(
        "content-security-policy"
    )
    shell = opened.text.split("srcdoc=", 1)[0]
    assert "Content-Security-Policy" not in shell
    vendor = client.get("/app-vendor/htmx-2.0.11.min.js")
    assert vendor.headers.get("access-control-allow-origin") == "null"
    missing = client.get("/app-vendor/missing.js")
    assert missing.status_code == 404
    hidden = client.get("/app-vendor/.hidden.js")
    assert hidden.status_code == 404


def test_frame_loads_vendor_modules_without_the_token() -> None:
    from iterthink.services.bridge_fake import FakeBridge
    from iterthink.web.app import create_app

    client = TestClient(create_app(bridge=FakeBridge(), token="t"))
    three = client.get("/app-vendor/three/build/three.module.js")
    assert three.status_code == 200
    assert three.headers.get("access-control-allow-origin") == "null"
    assert client.get("/app-vendor/three/LICENSE").status_code == 404
    assert client.get("/app-vendor/three/%2E%2E/%2E%2E/app.js").status_code == 404
    assert client.get("/app/p-x").status_code == 401


def test_build_keep_and_revise_from_the_page(tmp_path: Path, project_dir: Path) -> None:
    client, project, slug = _page(tmp_path, project_dir)
    listed = client.get(f"/p/{project}/apps")
    assert "Build" in listed.text
    assert "Door notes" in listed.text
    kept = client.post(f"/p/{project}/apps/{slug}/keep", follow_redirects=False)
    assert kept.status_code == 303
    empty = client.post(f"/p/{project}/apps/{slug}/call", json={})
    assert "propose" in empty.text
    names = client.post(f"/p/{project}/apps/{slug}/call", json=["no"])
    assert names.status_code == 200
    changed = client.post(
        f"/p/{project}/apps/{slug}/revise", data={"ask": "rename it"}, follow_redirects=False
    )
    assert changed.status_code == 303
    dropped = client.post(f"/p/{project}/apps/{slug}/discard", follow_redirects=False)
    assert dropped.headers["location"].endswith("/apps")


def test_line_builds_the_app_and_opens_it(tmp_path: Path, project_dir: Path) -> None:
    client, project, _ = _page(tmp_path, project_dir)
    page = client.post(
        f"/p/{project}/line",
        data={"q": "Door schedule from the model"},
        headers={"HX-Request": "true"},
    )
    assert page.status_code == 200
    assert page.headers["hx-redirect"].startswith(f"/p/{project}/apps/")
    assert "Opened as app" in page.text
