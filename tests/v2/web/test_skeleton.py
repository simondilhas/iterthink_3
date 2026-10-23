"""The skeleton every UI slice builds on: auth, static files, error mapping, discovery."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from starlette.requests import Request

from iterthink.services.bridge import Conflict, NotFound
from iterthink.services.bridge_fake import FakeBridge
from iterthink.web.app import TOKEN_COOKIE, create_app, has_route, stylesheets, templates

from .conftest import TOKEN


def test_requests_without_token_are_refused() -> None:
    client = TestClient(create_app(bridge=FakeBridge(), token=TOKEN))
    assert client.get("/health").status_code == 401


def test_token_link_sets_cookie_and_redirects() -> None:
    client = TestClient(create_app(bridge=FakeBridge(), token=TOKEN), follow_redirects=False)
    response = client.get(f"/health?token={TOKEN}")
    assert response.status_code == 303
    assert response.headers["location"].endswith("/health")
    assert response.cookies.get(TOKEN_COOKIE) == TOKEN


def test_wrong_token_is_refused() -> None:
    client = TestClient(create_app(bridge=FakeBridge(), token=TOKEN))
    assert client.get("/health?token=nope").status_code == 401


def test_health_reports_bridge(client: TestClient) -> None:
    response = client.get("/health", headers={"accept": "application/json"})
    assert response.json() == {"ok": True, "bridge": "FakeBridge"}


def test_vendored_htmx_is_served_without_token() -> None:
    client = TestClient(create_app(bridge=FakeBridge(), token=TOKEN))
    response = client.get("/static/vendor/htmx-2.0.11.min.js")
    assert response.status_code == 200
    assert "htmx" in response.text[:2000]


def test_bridge_errors_map_to_status_and_fragment() -> None:
    app = create_app(bridge=FakeBridge(), token=TOKEN)
    extra = APIRouter()

    @extra.get("/boom/{kind}")
    def boom(kind: str) -> None:
        raise {"missing": NotFound("no such file"), "conflict": Conflict("already decided")}[kind]

    app.include_router(extra)
    client = TestClient(app, headers={"x-iterthink-token": TOKEN})
    html = client.get("/boom/missing", headers={"accept": "text/html"})
    assert html.status_code == 404
    assert 'role="alert"' in html.text
    assert "no such file" in html.text
    json_resp = client.get("/boom/conflict", headers={"accept": "application/json"})
    assert json_resp.status_code == 409
    assert json_resp.json() == {"error": "already decided"}


def test_base_template_loads_slice_stylesheets_and_knows_routes(client: TestClient) -> None:
    app = client.app
    router = APIRouter()

    @router.get("/probe", response_class=HTMLResponse, name="probe")
    def probe(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "base.html", {})

    app.include_router(router)  # type: ignore[attr-defined]
    html = client.get("/probe").text
    assert all(href in html for href in stylesheets())
    assert "/static/vendor/htmx-2.0.11.min.js" in html
    scope = {"type": "http", "app": app, "headers": []}
    assert has_route(Request(scope), "probe")
    assert not has_route(Request(scope), "does-not-exist")
