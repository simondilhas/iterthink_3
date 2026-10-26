"""Dictation is typing by voice: local, streamed, and never stored."""

from __future__ import annotations

import importlib.util
import wave
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from iterthink.services.bridge import Invalid
from iterthink.services.bridge_fake import FakeBridge
from iterthink.services.bridge_real import RealBridge
from iterthink.services.projects import read_yaml, write_yaml
from iterthink.services.settings import get
from iterthink.web.app import TOKEN_HEADER, create_app

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "audio" / "standard-de.wav"
TOKEN = "test-token"


class _Wav:
    """Plays a fixture. Nothing is written."""

    def __init__(self, path: Path) -> None:
        with wave.open(str(path), "rb") as handle:
            self.sample_rate = handle.getframerate()
            self._pcm = handle.readframes(handle.getnframes())

    def read(self, stopped: object) -> bytes:
        del stopped
        return self._pcm


def _bridge(tmp_path: Path) -> RealBridge:
    return RealBridge(state_dir=tmp_path / "state", machine="m-test")


def _client(bridge: RealBridge) -> TestClient:
    app = create_app(bridge=bridge, token=TOKEN, actor="user:ada")
    return TestClient(app, headers={TOKEN_HEADER: TOKEN})


def _values(project_dir: Path) -> Path:
    return project_dir / ".iterthink" / "settings" / "values.yaml"


def _require_voice() -> None:
    if importlib.util.find_spec("faster_whisper") is not None:
        return
    # CI only installs the dev extra. Failing here would turn the required
    # check red until that workflow installs `voice`. See the run report.
    pytest.skip("voice extra is not installed")


def _script() -> str:
    return (Path("iterthink/web/static/js/it-dictation.js")).read_text(encoding="utf-8")


def _page_has_script() -> None:
    head = Path("iterthink/web/templates/home/head.html").read_text(encoding="utf-8")
    assert "it-dictation.js" in head


def test_transcribes_fixture_standard_german(tmp_path: Path, project_dir: Path) -> None:
    _require_voice()
    from iterthink.ai.local_stt import pcm_to_audio, resolve_root, transcribe, weights_ready
    from iterthink.services.projects import default_state_dir

    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    assert get(project_dir, "dictation.model").value == "small"
    assert get(project_dir, "dictation.language").value == "auto"
    data = read_yaml(_values(project_dir))
    data["dictation.model"] = "tiny"
    data["dictation.language"] = "de"
    write_yaml(_values(project_dir), data)
    assert weights_ready(tmp_path, "tiny") is False
    root = resolve_root(tmp_path / "state", "tiny", default_state_dir())
    if not weights_ready(root, "tiny"):
        pytest.skip("whisper tiny is not downloaded yet")
    silence = b"\x00\x00" * 160
    assert len(pcm_to_audio(silence, 16000)) == 160
    assert len(pcm_to_audio(silence, 8000)) == 320
    assert list(transcribe(b"", 16000, language="de", model="tiny", state_dir=tmp_path)) == []
    device = _Wav(FIXTURE)
    bridge.use_dictation_device(device)
    bridge.dictation_start(project)
    heard = [data for event, data in bridge.dictation_events(project) if event == "transcript"]
    text = " ".join(heard).casefold()
    assert "guten tag" in text
    assert "test" in text
    again = list(
        transcribe(
            device.read(lambda: False),
            device.sample_rate,
            language="de",
            model="tiny",
            state_dir=tmp_path / "state",
            fallback=default_state_dir(),
        )
    )
    assert again


def test_transcript_streams_into_field_without_enter(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id

    def fake(
        pcm: bytes, rate: int, language: str | None, model: str, state_dir: Path, fallback: Path
    ) -> Iterator[str]:
        del pcm, rate, language, model, state_dir, fallback
        yield "Guten"
        yield "Tag"

    bridge.use_transcriber(fake)
    bridge.use_dictation_device(_Wav(FIXTURE))
    client = _client(bridge)
    started = client.post(f"/p/{project}/dictation/start")
    assert started.status_code == 200
    stream = client.get(f"/p/{project}/dictation/events")
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "event: transcript\ndata: Guten\n" in stream.text
    assert "event: transcript\ndata: Tag\n" in stream.text
    assert "event: done\n" in stream.text
    script = _script()
    assert "setRangeText" in script
    assert "requestSubmit" not in script
    assert ".submit(" not in script
    assert "new KeyboardEvent" not in script
    _page_has_script()


def test_capture_runs_in_python_not_webview() -> None:
    source = Path("iterthink/services/dictation.py").read_text(encoding="utf-8")
    route = Path("iterthink/web/routes/dictation.py").read_text(encoding="utf-8")
    script = _script()
    assert "sounddevice" in source
    assert "getUserMedia" not in script
    assert "MediaRecorder" not in script
    assert "SpeechRecognition" not in script
    assert "dictation/start" in route
    assert "dictation/stop" in route
    from iterthink.services.dictation import LiveCapture

    class _Stream:
        def __init__(self, callback: object) -> None:
            self._callback = callback

        def __enter__(self) -> _Stream:
            callback = self._callback
            if callable(callback):
                callback(b"\x01\x00", 1, None, None)
            return self

        def __exit__(self, *args: object) -> None:
            del args

    class _Device:
        def __init__(self) -> None:
            self.kwargs: dict[str, object] = {}

        def RawInputStream(self, **kwargs: object) -> _Stream:
            self.kwargs = kwargs
            return _Stream(kwargs.get("callback"))

    device = _Device()
    seen: dict[str, int] = {"n": 0}

    def stopped() -> bool:
        seen["n"] += 1
        return seen["n"] > 1

    import iterthink.services.dictation as dictation

    original = dictation._sounddevice
    dictation._sounddevice = lambda: device
    try:
        pcm = LiveCapture().read(stopped)
    finally:
        dictation._sounddevice = original
    assert pcm == b"\x01\x00"
    assert device.kwargs.get("channels") == 1
    assert device.kwargs.get("dtype") == "int16"


def test_default_key_is_mod_shift_space_and_configurable(tmp_path: Path, project_dir: Path) -> None:
    from iterthink.services.dictation import DEFAULT_KEY, hands_free, hotkey

    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    assert DEFAULT_KEY == "Mod+Shift+Space"
    assert hotkey(None) == DEFAULT_KEY
    assert bridge.dictation_config(project) == f"{DEFAULT_KEY}\n0"
    assert "Mod+Shift+Space" in _script()
    assert "Ctrl+Space" not in _script()
    data = read_yaml(_values(project_dir))
    data["dictation.hotkey"] = "Ctrl+Space"
    write_yaml(_values(project_dir), data)
    assert hotkey(project_dir) == DEFAULT_KEY
    data["dictation.hotkey"] = "Mod+Shift+D"
    data["dictation.hands_free"] = "1"
    write_yaml(_values(project_dir), data)
    assert hotkey(project_dir) == "Mod+Shift+D"
    assert hands_free(project_dir) is True
    assert bridge.dictation_config(project) == "Mod+Shift+D\n1"
    client = _client(bridge)
    assert client.get(f"/p/{project}/dictation/key").text == "Mod+Shift+D\n1"
    assert client.get("/dictation/key").text == f"{DEFAULT_KEY}\n0"


def test_no_network_during_dictation(tmp_path: Path, project_dir: Path) -> None:
    _require_voice()
    from iterthink.ai.local_stt import resolve_root, weights_ready
    from iterthink.services.projects import default_state_dir

    root = resolve_root(tmp_path / "state", "tiny", default_state_dir())
    if not weights_ready(root, "tiny"):
        pytest.skip("whisper tiny is not downloaded yet")
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    data = read_yaml(_values(project_dir))
    data["dictation.model"] = "tiny"
    data["dictation.language"] = "de"
    write_yaml(_values(project_dir), data)
    bridge.use_dictation_device(_Wav(FIXTURE))
    bridge.dictation_start(project)
    heard = [item for event, item in bridge.dictation_events(project) if event == "transcript"]
    assert heard


def test_audio_not_written_to_disk(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    before = {path for path in project_dir.rglob("*") if path.is_file()}

    def fake(
        pcm: bytes, rate: int, language: str | None, model: str, state_dir: Path, fallback: Path
    ) -> Iterator[str]:
        assert pcm
        assert rate
        del language, model, state_dir, fallback
        yield "Guten Tag"

    bridge.use_transcriber(fake)
    bridge.use_dictation_device(_Wav(FIXTURE))
    bridge.dictation_start(project)
    heard = [item for event, item in bridge.dictation_events(project) if event == "transcript"]
    after = {path for path in project_dir.rglob("*") if path.is_file()}
    assert heard == ["Guten Tag"]
    assert after == before
    source = Path("iterthink/services/dictation.py").read_text(encoding="utf-8")
    stt = Path("iterthink/ai/local_stt.py").read_text(encoding="utf-8")
    assert "open(" not in source or '"wb"' not in source
    assert ".wav" not in stt


def test_voice_source_recorded_on_following_ai_action(tmp_path: Path, project_dir: Path) -> None:
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id

    def fake(
        pcm: bytes, rate: int, language: str | None, model: str, state_dir: Path, fallback: Path
    ) -> Iterator[str]:
        del pcm, rate, language, model, state_dir, fallback
        yield "new document Fire concept"

    bridge.use_transcriber(fake)
    bridge.use_dictation_device(_Wav(FIXTURE))
    bridge.classify_line(project, "find the hall", None, "user:ada")
    bridge.dictation_start(project)
    list(bridge.dictation_events(project))
    bridge.classify_line(project, "new document Fire concept", None, "user:ada")
    bridge.classify_line(project, "find the hall", None, "user:ada")
    lines = [
        line
        for path in (project_dir / ".iterthink" / "log").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
        if '"type":"intent"' in line
    ]
    assert len(lines) >= 3
    assert '"source":"typed"' in lines[0]
    assert '"source":"voice"' in lines[1]
    assert '"source":"typed"' in lines[2]
    assert "audio" not in lines[1]
    assert "avg_logprob" not in lines[1]
    assert "probability" not in lines[1]
    assert "RIFF" not in lines[1]
    missing = FakeBridge()
    app = create_app(bridge=missing, token=TOKEN, actor="user:ada")
    client = TestClient(app, headers={TOKEN_HEADER: TOKEN})
    assert client.post("/dictation/start").status_code == 404


class _Silent:
    sample_rate = 16000

    def read(self, stopped: object) -> bytes:
        del stopped
        return b""


def test_dictation_edges(
    tmp_path: Path, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from iterthink.ai import local_stt
    from iterthink.services.dictation import (
        hands_free,
        hotkey,
        language,
        mark_voice,
        model_name,
        take_source,
    )

    assert language(None) is None
    assert model_name(None) == "small"
    assert pcm_edges(tmp_path, monkeypatch) == ["Hallo"]
    folder = tmp_path / "models" / "whisper" / "models--Systran--faster-whisper-tiny"
    folder.mkdir(parents=True)
    assert local_stt.resolve_root(tmp_path, "tiny", None) == folder.parent
    empty = tmp_path / "empty"
    assert local_stt.resolve_root(empty, "tiny", None) == local_stt.model_root(empty)
    assert local_stt.resolve_root(empty, "tiny", empty) == local_stt.model_root(empty)
    mark_voice(None)
    assert take_source(project_dir) == "voice"
    assert take_source(project_dir) == "typed"
    workspace = project_dir.parent / ".iterthink" / "settings" / "values.yaml"
    write_yaml(workspace, {"dictation.hotkey": "Mod+Shift+K", "dictation.hands_free": "yes"})
    assert hotkey(project_dir) == "Mod+Shift+K"
    assert hands_free(project_dir) is True
    data = read_yaml(_values(project_dir))
    data["dictation.hotkey"] = "Shift"
    data["dictation.language"] = "zz"
    data["dictation.model"] = "huge"
    write_yaml(_values(project_dir), data)
    assert hotkey(project_dir) == "Mod+Shift+Space"
    assert language(project_dir) is None
    assert model_name(project_dir) == "small"
    bridge = _bridge(tmp_path)
    project = bridge.make_project(project_dir).id
    bridge.dictation_stop(project)
    with pytest.raises(Invalid):
        list(bridge.dictation_events(project))
    bridge.use_dictation_device(_Silent())
    bridge.dictation_start(project)
    bridge.dictation_stop(project)
    assert list(bridge.dictation_events(project))
    bridge.classify_line(project, "find the hall", None, "user:ada")

    def spaces(
        pcm: bytes, rate: int, chosen: str | None, size: str, state_dir: Path, fallback: Path
    ) -> Iterator[str]:
        del pcm, rate, chosen, size, state_dir, fallback
        yield "   "

    bridge.use_transcriber(spaces)
    bridge.use_dictation_device(_Wav(FIXTURE))
    bridge.dictation_start(project)
    assert not [item for event, item in bridge.dictation_events(project) if event == "transcript"]

    def blank(
        pcm: bytes, rate: int, chosen: str | None, size: str, state_dir: Path, fallback: Path
    ) -> Iterator[str]:
        del pcm, rate, chosen, size, state_dir, fallback
        yield "  "
        yield "Hallo"

    def broken(
        pcm: bytes, rate: int, chosen: str | None, size: str, state_dir: Path, fallback: Path
    ) -> Iterator[str]:
        del pcm, rate, chosen, size, state_dir, fallback
        raise RuntimeError("dictation failed")

    bridge.use_transcriber(blank)
    bridge.use_dictation_device(_Wav(FIXTURE))
    bridge.dictation_start(project)
    bridge.dictation_start(project)
    heard = [item for event, item in bridge.dictation_events(project) if event == "transcript"]
    assert heard == ["Hallo"]
    bridge.use_transcriber(broken)
    bridge.dictation_start(project)
    assert any(event == "done" for event, _item in bridge.dictation_events(project))
    client = _client(bridge)
    assert client.post("/dictation/start").status_code == 200
    assert client.post(f"/p/{project}/dictation/stop").status_code == 200
    assert client.post("/dictation/stop").status_code == 200
    assert "event: done" in client.get("/dictation/events").text
    if importlib.util.find_spec("sounddevice") is not None:
        from iterthink.services import dictation as dictation_mod

        assert dictation_mod._sounddevice() is not None


class _FakeModel:
    def transcribe(self, audio: object, **kwargs: object) -> tuple[list[object], None]:
        del audio, kwargs
        return [_Blank("  "), _Blank("Hallo")], None


class _Blank:
    def __init__(self, text: str) -> None:
        self.text = text


def pcm_edges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from iterthink.ai import local_stt

    assert local_stt.pcm_to_audio(b"", 16000).size == 0
    assert local_stt.pcm_to_audio(b"\x00\x00", 10**9).size == 0
    empty = local_stt.transcribe(
        b"\x00\x00", 10**9, language=None, model="tiny", state_dir=tmp_path
    )
    assert list(empty) == []
    monkeypatch.setattr(local_stt, "_load", lambda root, size: _FakeModel())
    heard = local_stt.transcribe(
        b"\x00\x00" * 160, 16000, language=None, model="tiny", state_dir=tmp_path
    )
    return list(heard)
