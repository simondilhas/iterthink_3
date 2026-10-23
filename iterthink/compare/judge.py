"""Semantic tie-break for paragraph compare. No UI."""

from __future__ import annotations

from typing import Any, Literal

from iterthink.ai.ollama_util import chat_response_text

SemanticKind = Literal["STABLE", "NEW"]
RewriteVsMajor = Literal["rephrased", "modified"]


def _clip(s: str, max_len: int = 2800) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


async def judge_semantic(chat: Any, model: str, original: str, revised: str) -> SemanticKind:
    """Ask the configured chat backend whether the revision shifts intent (NEW) or not (STABLE)."""
    messages = [
        {
            "role": "system",
            "content": "Reply with exactly one word: STABLE or NEW. No punctuation.",
        },
        {
            "role": "user",
            "content": (
                "Compare A vs B. STABLE = same core meaning and intent. "
                "NEW = main message, recommendation, or stance changed.\n\n"
                f"A:\n{_clip(original)}\n\nB:\n{_clip(revised)}"
            ),
        },
    ]
    try:
        resp = await chat.chat(model=model, messages=messages, stream=False)
        raw = (chat_response_text(resp) or "").strip().upper()
        for token in raw.replace(",", " ").split():
            if token in ("NEW", "STABLE"):
                return "NEW" if token == "NEW" else "STABLE"
    except BaseException:
        pass
    return "STABLE"


async def judge_rewritten_vs_major(chat: Any, model: str, original: str, revised: str) -> RewriteVsMajor:
    """LLM tie-break: surface rewrite vs deeper semantic rewrite (rewritten)."""
    messages = [
        {
            "role": "system",
            "content": "Reply with exactly one word: rewritten or major. No punctuation.",
        },
        {
            "role": "user",
            "content": (
                "Compare paragraph A vs B after a heavy text edit.\n"
                "major = same core meaning and intent, mostly rephrase or reorder.\n"
                "rewritten = main point, recommendation, facts, or stance materially changed.\n\n"
                f"A:\n{_clip(original)}\n\nB:\n{_clip(revised)}"
            ),
        },
    ]
    try:
        resp = await chat.chat(model=model, messages=messages, stream=False)
        raw = (chat_response_text(resp) or "").strip().lower()
        for token in raw.replace(",", " ").split():
            if "rewritten" in token:
                return "rephrased"
            if token == "major" or token.startswith("major"):
                return "modified"
    except BaseException:
        pass
    return "modified"
