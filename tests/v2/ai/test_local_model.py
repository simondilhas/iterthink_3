"""The local Ollama model behind the line and chats, tested against a fake client."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from iterthink import config
from iterthink.ai.local_model import LINE_MODEL, LocalModel, connect


class _Client:
    def __init__(self, reply: str = "chat 0.8", fail: BaseException | None = None) -> None:
        self.reply = reply
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def chat(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        if self.fail is not None:
            raise self.fail
        if kwargs.get("stream"):
            return iter([{"message": {"content": "Hel"}}, {"message": {"content": "lo"}}])
        return {"message": {"content": self.reply}}


class _Bridge:
    def __init__(self) -> None:
        self.line: object = None
        self.chat: object = None

    def use_intent_model(self, router: object) -> None:
        self.line = router

    def use_model(self, router: object) -> None:
        self.chat = router


def test_complete_sends_system_and_line_to_the_named_model() -> None:
    client = _Client("document 0.9")
    model = LocalModel("qwen2.5:3b", client=client)
    assert model.complete("Classify.", "Fire concept", "local") == "document 0.9"
    call = client.calls[0]
    assert call["model"] == "qwen2.5:3b"
    assert call["stream"] is False
    assert call["messages"] == [
        {"role": "system", "content": "Classify."},
        {"role": "user", "content": "Fire concept"},
    ]
    assert model.tier == "local"


def test_unreachable_model_answers_empty() -> None:
    model = LocalModel("qwen2.5:3b", client=_Client(fail=ConnectionError("refused")))
    assert model.complete("Classify.", "Fire concept", "local") == ""


def test_stream_yields_the_pieces() -> None:
    model = LocalModel("llama3:8b", client=_Client())
    parts: Iterator[str] = model.stream("Answer.", "Hi", "local")
    assert list(parts) == ["Hel", "lo"]


def test_connect_gives_the_line_and_chats_a_model() -> None:
    bridge = _Bridge()
    connect(bridge, client=_Client(), warm=False)
    assert isinstance(bridge.line, LocalModel)
    assert bridge.line.model == LINE_MODEL == "qwen2.5:3b"
    assert isinstance(bridge.chat, LocalModel)
    assert bridge.chat.model == config.DEFAULT_OLLAMA_MODEL


def test_connect_skips_a_bridge_without_models() -> None:
    connect(object(), client=_Client(), warm=False)
