"""The local Ollama model behind the line and chats. Nothing here leaves the machine."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Any

import httpx
from ollama import Client, ResponseError

from iterthink import config
from iterthink.ai.ollama_util import chat_response_text, chat_stream_delta

LINE_MODEL = "qwen2.5:3b"
_KEEP_ALIVE = "30m"
_TIMEOUT = 60.0
_STATUS_TIMEOUT = 3.0


def _messages(system: str, user: str) -> list[dict[str, str]]:
    found = [{"role": "system", "content": system}] if system else []
    return [*found, {"role": "user", "content": user}]


class LocalModel:
    """`complete` for the line, `stream` for chats. Only the local tier."""

    tier = "local"

    def __init__(self, model: str, client: Any | None = None, host: str | None = None) -> None:
        self.model = model
        if client is None:
            client = Client(host or config.OLLAMA_HOST, timeout=_TIMEOUT)
        self._client = client

    def complete(self, system: str, user: str, tier: str) -> str:
        """The answer, or "" when Ollama is not running or the model is missing."""
        try:
            reply = self._client.chat(
                model=self.model,
                messages=_messages(system, user),
                stream=False,
                keep_alive=_KEEP_ALIVE,
                options={"temperature": 0},
            )
        except (ConnectionError, ResponseError, httpx.HTTPError):
            return ""
        return chat_response_text(reply)

    def stream(self, system: str, user: str, tier: str) -> Iterator[str]:
        parts = self._client.chat(
            model=self.model,
            messages=_messages(system, user),
            stream=True,
            keep_alive=_KEEP_ALIVE,
        )
        for part in parts:
            text = chat_stream_delta(part)
            if text:
                yield text


def connect(
    bridge: object,
    *,
    line_model: str = LINE_MODEL,
    chat_model: str | None = None,
    host: str | None = None,
    client: Any | None = None,
    warm: bool = True,
) -> None:
    """Give the line and chats their local model. `warm` loads the line model in the background."""
    line = LocalModel(line_model, client, host)
    chat = LocalModel(chat_model or config.DEFAULT_OLLAMA_MODEL, client, host)
    for method, router in (("use_intent_model", line), ("use_model", chat)):
        setter = getattr(bridge, method, None)
        if callable(setter):
            setter(router)
    if warm:
        threading.Thread(
            target=line.complete, args=("", "ok", "local"), name="iterthink-warm", daemon=True
        ).start()


def _model_names(listing: object) -> tuple[str, ...]:
    items = listing.get("models") if isinstance(listing, dict) else getattr(listing, "models", [])
    names: list[str] = []
    for item in items if isinstance(items, list) else []:
        name = item.get("model") or item.get("name") if isinstance(item, dict) else None
        name = name or getattr(item, "model", None)
        if isinstance(name, str) and name:
            names.append(name)
    return tuple(sorted(names))


def installed_models(client: Any | None = None, host: str | None = None) -> tuple[str, ...] | None:
    """The models Ollama has, or None when it does not answer."""
    if client is None:
        client = Client(host or config.OLLAMA_HOST, timeout=_STATUS_TIMEOUT)
    try:
        return _model_names(client.list())
    except (ConnectionError, ResponseError, httpx.HTTPError, OSError):
        return None
