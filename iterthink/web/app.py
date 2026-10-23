"""App factory. Human-owned skeleton: slices add route modules, not edit this file.

Every module in `iterthink/web/routes/` that defines `router` is mounted
automatically, so parallel slices never touch the same file.
"""

from __future__ import annotations

import importlib
import pkgutil
import secrets
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from iterthink.services.bridge import (
    Bridge,
    BridgeError,
    Conflict,
    Forbidden,
    Invalid,
    NotFound,
    get_bridge,
)
from iterthink.web import routes

HERE = Path(__file__).parent
TOKEN_COOKIE = "iterthink_token"  # noqa: S105 - a cookie name, not a secret
TOKEN_HEADER = "x-iterthink-token"  # noqa: S105 - a header name
PUBLIC_PREFIXES = ("/static/",)

STATUS = {NotFound: 404, Forbidden: 403, Conflict: 409, Invalid: 422}

templates = Jinja2Templates(directory=str(HERE / "templates"))


def stylesheets() -> list[str]:
    """Per-slice stylesheets in static/css/, loaded by base.html after app.css."""
    return sorted(f"/static/css/{p.name}" for p in (HERE / "static" / "css").glob("*.css"))


def _route_names(routes: object) -> Iterator[str]:
    for route in routes if isinstance(routes, list) else []:
        name = getattr(route, "name", None)
        if isinstance(name, str):
            yield name
        for attr in ("routes", "original_router"):  # mounts and included routers
            child = getattr(route, attr, None)
            if child is not None and child is not route:
                yield from _route_names(getattr(child, "routes", child))


def has_route(request: Request, name: str) -> bool:
    """Lets a template link to another slice's page only once that slice exists."""
    return name in _route_names(request.app.router.routes)


templates.env.globals["stylesheets"] = stylesheets
templates.env.globals["has_route"] = has_route


def bridge_of(request: Request) -> Bridge:
    """Dependency: the bridge for this app instance."""
    bridge: Bridge = request.app.state.bridge
    return bridge


def actor_of(request: Request) -> str:
    """Dependency: who is acting. Single local user until accounts exist."""
    actor: str = request.app.state.actor
    return actor


def _wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "") or "hx-request" in request.headers


def create_app(
    bridge: Bridge | None = None, token: str | None = None, actor: str = "user:local"
) -> FastAPI:
    app = FastAPI(title="iterthink", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.bridge = bridge if bridge is not None else get_bridge()
    app.state.token = token or secrets.token_urlsafe(24)
    app.state.actor = actor
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    @app.middleware("http")
    async def require_token(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)
        expected = request.app.state.token
        given = request.query_params.get("token")
        if given is not None and secrets.compare_digest(given, expected):
            target = request.url.remove_query_params("token")
            response = RedirectResponse(str(target), status_code=303)
            response.set_cookie(TOKEN_COOKIE, expected, httponly=True, samesite="strict")
            return response
        presented = request.cookies.get(TOKEN_COOKIE) or request.headers.get(TOKEN_HEADER) or ""
        if not secrets.compare_digest(presented, expected):
            return Response(
                "Open iterthink from its window or the link it printed.", status_code=401
            )
        return await call_next(request)

    @app.exception_handler(BridgeError)
    async def bridge_error(request: Request, exc: BridgeError) -> Response:
        status = next((code for cls, code in STATUS.items() if isinstance(exc, cls)), 400)
        if _wants_html(request):
            return templates.TemplateResponse(
                request, "partials/error.html", {"message": str(exc)}, status_code=status
            )
        return JSONResponse({"error": str(exc)}, status_code=status)

    for module in pkgutil.iter_modules(routes.__path__):
        loaded = importlib.import_module(f"{routes.__name__}.{module.name}")
        router = getattr(loaded, "router", None)
        if router is not None:
            app.include_router(router)

    @app.get("/health", response_class=JSONResponse)
    async def health(request: Request) -> dict[str, object]:
        return {"ok": True, "bridge": type(request.app.state.bridge).__name__}

    @app.exception_handler(404)
    async def not_found(request: Request, exc: Exception) -> Response:
        if _wants_html(request):
            return HTMLResponse(
                templates.get_template("partials/error.html").render(message="Not found"),
                status_code=404,
            )
        return JSONResponse({"error": "not found"}, status_code=404)

    return app
