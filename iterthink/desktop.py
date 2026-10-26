"""Local window. The page is the web app on 127.0.0.1 with a token in the URL."""

from __future__ import annotations

import http.client
import socket
import threading
import time
from typing import Any

import uvicorn

from iterthink.web.app import create_app


class FolderApi:
    """Exposed to the page as `window.pywebview.api`."""

    def __init__(self, webview: Any) -> None:
        self._webview = webview

    def choose_folder(self) -> str | None:
        """The folder the person picked, or None if they cancelled."""
        windows = self._webview.windows
        if not windows:
            return None
        chosen = windows[0].create_file_dialog(self._webview.FOLDER_DIALOG)
        if not chosen:
            return None
        first = chosen[0]
        return str(first) if first else None


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def _health_ok(port: int, token: str) -> bool:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
    try:
        conn.request("GET", "/health", headers={"x-iterthink-token": token})
        return conn.getresponse().status == 200
    except OSError:
        return False
    finally:
        conn.close()


def _wait_until_up(port: int, token: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if _health_ok(port, token):
            return
        time.sleep(0.05)
    raise RuntimeError("iterthink did not start")


def launch(webview: Any, *, local_model: bool = False) -> None:
    """Serve the app and open it. Returns when the window closes."""
    app = create_app()
    connect = getattr(app.state.bridge, "use_local_model", None)
    if local_model and callable(connect):
        connect()
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, name="iterthink-http", daemon=True)
    thread.start()
    token = str(app.state.token)
    try:
        _wait_until_up(port, token)
        url = f"http://127.0.0.1:{port}/?token={token}"
        webview.create_window("iterthink", url, js_api=FolderApi(webview))
        webview.start()
    finally:
        server.should_exit = True
        thread.join(timeout=3)


def main() -> None:
    import webview

    launch(webview, local_model=True)


if __name__ == "__main__":
    main()
