"""Local speech to text. The model is downloaded once into the machine state directory."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

_RATE = 16000
_LOADED: dict[tuple[str, str], Any] = {}


def model_root(state_dir: Path) -> Path:
    """Where this machine keeps whisper weights."""
    return state_dir / "models" / "whisper"


def weights_ready(root: Path, size: str) -> bool:
    """True when this size was already downloaded."""
    return (root / f"models--Systran--faster-whisper-{size}").is_dir()


def resolve_root(state_dir: Path, size: str, fallback: Path | None) -> Path:
    """The state directory, or the machine directory when that already has the model."""
    local = model_root(state_dir)
    if weights_ready(local, size):
        return local
    if fallback is not None:
        shared = model_root(fallback)
        if shared != local and weights_ready(shared, size):
            return shared
    return local


def pcm_to_audio(pcm: bytes, sample_rate: int) -> Any:
    """Mono float32 at 16 kHz. The samples stay in memory."""
    import numpy as np

    if not pcm:
        return np.zeros(0, dtype=np.float32)
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    if sample_rate == _RATE:
        return audio
    target = int(len(audio) * _RATE / sample_rate)
    if target <= 0:
        return np.zeros(0, dtype=np.float32)
    old = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
    new = np.linspace(0.0, 1.0, num=target, endpoint=False)
    return np.interp(new, old, audio).astype(np.float32)


def _load(root: Path, size: str) -> Any:
    key = (str(root), size)
    found = _LOADED.get(key)
    if found is not None:
        return found
    from faster_whisper import WhisperModel

    root.mkdir(parents=True, exist_ok=True)
    loaded = WhisperModel(
        size,
        device="cpu",
        compute_type="int8",
        download_root=str(root),
        local_files_only=weights_ready(root, size),
    )
    _LOADED[key] = loaded
    return loaded


def transcribe(
    pcm: bytes,
    sample_rate: int,
    *,
    language: str | None,
    model: str,
    state_dir: Path,
    fallback: Path | None = None,
) -> Iterator[str]:
    """Yield each recognised phrase. Confidence stays with the model."""
    if not pcm:
        return
    audio = pcm_to_audio(pcm, sample_rate)
    if getattr(audio, "size", 0) == 0:
        return
    whisper = _load(resolve_root(state_dir, model, fallback), model)
    segments, _info = whisper.transcribe(
        audio,
        language=language,
        vad_filter=False,
        condition_on_previous_text=False,
    )
    for segment in segments:
        text = str(segment.text).strip()
        if text:
            yield text
