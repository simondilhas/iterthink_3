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


def _messages(system: str, user: str) -> list[dict[str, str]]:
    found = [{"role": "system", "content": system}] if system else []
    return [*found, {"role": "user", "content": user}]


class LocalModel:
    """`complete` for the line, `stream` for chats. Only the local tier."""

    tier = "local"

    def __init__(self, model: str, client: Any | None = None) -> None:
        self.model = model
        self._client = (
            client if client is not None else Client(config.OLLAMA_HOST, timeout=_TIMEOUT)
        )

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


def connect(bridge: object, *, client: Any | None = None, warm: bool = True) -> None:
    """Give the line and chats their local model. `warm` loads the line model in the background."""
    line = LocalModel(LINE_MODEL, client)
    for method, router in (
        ("use_intent_model", line),
        ("use_model", LocalModel(config.DEFAULT_OLLAMA_MODEL, client)),
    ):
        setter = getattr(bridge, method, None)
        if callable(setter):
            setter(router)
    if warm:
        threading.Thread(
            target=line.complete, args=("", "ok", "local"), name="iterthink-warm", daemon=True
        ).start()
