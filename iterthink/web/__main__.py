"""Run the UI in a browser: `uv run python -m iterthink.web` (prints the link).

The desktop window (`iterthink/desktop.py`, slice A1) starts the same app.
"""

from __future__ import annotations

import socket

import uvicorn

from iterthink.web.app import create_app


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def main() -> None:
    app = create_app()
    connect = getattr(app.state.bridge, "use_local_model", None)
    if callable(connect):
        connect()
    port = free_port()
    print(f"iterthink: http://127.0.0.1:{port}/?token={app.state.token}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
