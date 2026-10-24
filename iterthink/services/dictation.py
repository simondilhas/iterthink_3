"""Capture speech in Python and stream the transcript. Audio is never stored."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Protocol, cast

from iterthink.ai import local_stt
from iterthink.services.bridge import Invalid
from iterthink.services.projects import default_state_dir, read_yaml
from iterthink.services.settings import get

DEFAULT_KEY = "Mod+Shift+Space"
_LANGS = {"de", "en", "fr", "it"}
_SIZES = {"tiny", "base", "small", "medium", "large-v3"}
_VOICE: set[str] = set()
_GLOBAL = False
_SESSIONS: dict[str, _Run] = {}


class _Capture(Protocol):
    sample_rate: int

    def read(self, stopped: Callable[[], bool]) -> bytes: ...


class _Host(Protocol):
    state_dir: Path

    def _root(self, project: str) -> Path: ...


_Transcribe = Callable[[bytes, int, str | None, str, Path, Path], Iterator[str]]


class _Run:
    def __init__(self) -> None:
        self.stop = threading.Event()
        self.queue: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self.thread: threading.Thread | None = None


def mark_voice(project_dir: Path | None) -> None:
    """The next AI action in this project was spoken."""
    global _GLOBAL
    if project_dir is None:
        _GLOBAL = True
        return
    _VOICE.add(str(project_dir.resolve()))


def take_source(project_dir: Path) -> str:
    """`voice` once after dictation, otherwise `typed`."""
    global _GLOBAL
    if _GLOBAL:
        _GLOBAL = False
        return "voice"
    key = str(project_dir.resolve())
    if key in _VOICE:
        _VOICE.discard(key)
        return "voice"
    return "typed"


def _layer(project_dir: Path | None, key: str) -> str | None:
    if project_dir is None:
        return None
    own = read_yaml(project_dir / ".iterthink" / "settings" / "values.yaml").get(key)
    if isinstance(own, str) and own:
        return own
    parent = project_dir.parent / ".iterthink" / "settings" / "values.yaml"
    workspace = read_yaml(parent).get(key)
    if isinstance(workspace, str) and workspace:
        return workspace
    return None


def _allowed(value: str | None) -> bool:
    if not value or "+" not in value:
        return False
    parts = value.split("+")
    bare_ctrl = parts[0] == "Ctrl" and parts[-1] == "Space"
    if bare_ctrl and "Shift" not in parts and "Mod" not in parts:
        return False
    last = parts[-1]
    return last == "Space" or len(last) == 1


def hotkey(project_dir: Path | None) -> str:
    """Hold key. Ctrl+Space is refused because it switches the input source."""
    found = _layer(project_dir, "dictation.hotkey")
    if found is not None and _allowed(found):
        return found
    return DEFAULT_KEY


def hands_free(project_dir: Path | None) -> bool:
    """Optional toggle. The default is hold to talk."""
    return _layer(project_dir, "dictation.hands_free") in {"1", "true", "yes", "on"}


def language(project_dir: Path | None) -> str | None:
    """A fixed language, or None when settings say auto."""
    if project_dir is None:
        return None
    raw = str(get(project_dir, "dictation.language").value)
    return raw if raw in _LANGS else None


def model_name(project_dir: Path | None) -> str:
    """Whisper size from settings. Unknown values use small."""
    if project_dir is None:
        return "small"
    raw = str(get(project_dir, "dictation.model").value)
    return raw if raw in _SIZES else "small"


def _sounddevice() -> object:
    import sounddevice as sd

    return sd


class LiveCapture:
    """Microphone capture through sounddevice. The buffer stays in memory."""

    sample_rate = 16000

    def read(self, stopped: Callable[[], bool]) -> bytes:
        device = _sounddevice()
        chunks: list[bytes] = []

        def callback(indata: bytes, frames: int, time_info: object, status: object) -> None:
            del frames, time_info, status
            chunks.append(bytes(indata))

        stream = device.RawInputStream(  # type: ignore[attr-defined]
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            callback=callback,
        )
        with stream:
            while not stopped():
                time.sleep(0.05)
        return b"".join(chunks)


def _default_transcriber(
    pcm: bytes,
    rate: int,
    chosen: str | None,
    size: str,
    state_dir: Path,
    fallback: Path,
) -> Iterator[str]:
    return local_stt.transcribe(
        pcm,
        rate,
        language=chosen,
        model=size,
        state_dir=state_dir,
        fallback=fallback,
    )


def _speak(
    run: _Run,
    device: _Capture,
    root: Path | None,
    state_dir: Path,
    transcriber: _Transcribe,
) -> None:
    try:
        _fill(run, device, root, state_dir, transcriber)
    except Exception:
        return
    finally:
        run.queue.put(("done", "end"))
        run.queue.put(None)


def _fill(
    run: _Run,
    device: _Capture,
    root: Path | None,
    state_dir: Path,
    transcriber: _Transcribe,
) -> None:
    run.queue.put(("state", "listening"))
    pcm = device.read(run.stop.is_set)
    if not pcm:
        return
    run.queue.put(("state", "transcribing"))
    spoken = False
    pieces = transcriber(
        pcm, device.sample_rate, language(root), model_name(root), state_dir, default_state_dir()
    )
    for piece in pieces:
        text = " ".join(piece.split())
        if text:
            spoken = True
            run.queue.put(("transcript", text))
    if spoken:
        mark_voice(root)


class DictationBridge:
    """Dictation methods on the real bridge."""

    _dictation_device: _Capture | None = None
    _transcriber: _Transcribe | None = None

    def use_dictation_device(self, device: _Capture) -> None:
        self._dictation_device = device

    def use_transcriber(self, transcriber: _Transcribe) -> None:
        self._transcriber = transcriber

    def dictation_config(self, project: str) -> str:
        root = _root_of(self, project)
        return f"{hotkey(root)}\n{'1' if hands_free(root) else '0'}"

    def dictation_start(self, project: str) -> None:
        host = cast(_Host, self)
        previous = _SESSIONS.get(project)
        if previous is not None:
            previous.stop.set()
        run = _Run()
        _SESSIONS[project] = run
        transcriber = self._transcriber or _default_transcriber
        device = self._dictation_device or LiveCapture()
        run.thread = threading.Thread(
            target=_speak,
            args=(run, device, _root_of(self, project), host.state_dir, transcriber),
            daemon=True,
        )
        run.thread.start()

    def dictation_stop(self, project: str) -> None:
        found = _SESSIONS.get(project)
        if found is not None:
            found.stop.set()

    def dictation_events(self, project: str) -> Iterator[tuple[str, str]]:
        found = _SESSIONS.get(project)
        if found is None:
            raise Invalid("dictation is not running")
        while True:
            item = found.queue.get()
            if item is None:
                _SESSIONS.pop(project, None)
                return
            yield item


def _root_of(bridge: object, project: str) -> Path | None:
    if not project:
        return None
    return cast(_Host, bridge)._root(project)
