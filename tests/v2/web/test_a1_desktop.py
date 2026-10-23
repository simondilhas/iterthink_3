"""Desktop window and the checked scripts."""

from __future__ import annotations

from pathlib import Path

from iterthink.desktop import FolderApi, launch


class _Window:
    def __init__(self) -> None:
        self.url = ""
        self.js_api: object | None = None

    def create_file_dialog(self, kind: object) -> list[str]:
        assert kind == 20
        return ["/tmp/chosen"]


class _Webview:
    FOLDER_DIALOG = 20

    def __init__(self) -> None:
        self.window = _Window()
        self.windows: list[_Window] = []
        self.started = False

    def create_window(self, title: str, url: str, js_api: object = None) -> _Window:
        assert title == "iterthink"
        self.window.url = url
        self.window.js_api = js_api
        self.windows.append(self.window)
        return self.window

    def start(self) -> None:
        self.started = True


def test_desktop_starts_server_and_window() -> None:
    webview = _Webview()
    launch(webview)
    assert webview.started
    assert "token=" in webview.window.url
    assert webview.window.url.startswith("http://127.0.0.1:")
    api = webview.window.js_api
    assert isinstance(api, FolderApi)
    assert api.choose_folder() == "/tmp/chosen"


def test_folder_picker_waits_for_pywebview() -> None:
    """pywebview injects `window.pywebview` after load and then fires `pywebviewready`."""
    script = Path("iterthink/web/static/js/it-folder-picker.js").read_text(encoding="utf-8")
    assert '"pywebviewready"' in script


def test_js_files_are_ts_checked() -> None:
    folder = Path("iterthink/web/static/js")
    scripts = sorted(folder.glob("*.js"))
    assert scripts
    for script in scripts:
        first = script.read_text(encoding="utf-8").splitlines()[0]
        assert first == "// @ts-check"
