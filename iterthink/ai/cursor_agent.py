"""Cloud Agents API v1. Tests pass a fake; this client is the real HTTP shape."""

from __future__ import annotations

import json
from typing import Protocol

import httpx

_BASE = "https://api.cursor.com"


class CursorError(Exception):
    """The Cloud Agents API refused the call or could not be reached."""


class CursorClient(Protocol):
    """The calls the runner makes. `auto_pr` is always false for a task."""

    def create_agent(
        self, agent_id: str, prompt: str, remote: str, model: str, key: str, *, auto_pr: bool
    ) -> dict[str, str]: ...

    def load_agent(self, agent_id: str, key: str) -> dict[str, str]: ...

    def stream(self, agent_id: str, run_id: str, key: str) -> list[dict[str, str]]: ...

    def get_run(self, agent_id: str, run_id: str, key: str) -> dict[str, str]: ...

    def follow_up(self, agent_id: str, prompt: str, key: str) -> dict[str, str]: ...

    def cancel(self, agent_id: str, run_id: str, key: str) -> None: ...


class HttpxCursor:
    """POST and GET against `https://api.cursor.com`. No other host."""

    def __init__(self, transport: httpx.BaseTransport | None = None, base: str = _BASE) -> None:
        self.base = base
        self.transport = transport

    def create_agent(
        self, agent_id: str, prompt: str, remote: str, model: str, key: str, *, auto_pr: bool
    ) -> dict[str, str]:
        payload: dict[str, object] = {
            "autoCreatePR": auto_pr,
            "id": agent_id,
            "prompt": {"text": prompt},
            "source": {"url": remote},
        }
        if model:
            payload["cursor_model"] = model
        data = self._request("POST", "/v1/agents", key, payload)
        if _exists(data):
            return {"error": "already exists", "id": agent_id, "run_id": "", "url": ""}
        return _view(data, agent_id)

    def load_agent(self, agent_id: str, key: str) -> dict[str, str]:
        return _view(self._request("GET", f"/v1/agents/{agent_id}", key, None), agent_id)

    def stream(self, agent_id: str, run_id: str, key: str) -> list[dict[str, str]]:
        text = self._text("GET", f"/v1/agents/{agent_id}/runs/{run_id}/stream", key)
        return _events(text)

    def get_run(self, agent_id: str, run_id: str, key: str) -> dict[str, str]:
        path = f"/v1/agents/{agent_id}/runs/{run_id}"
        return _view(self._request("GET", path, key, None), agent_id)

    def follow_up(self, agent_id: str, prompt: str, key: str) -> dict[str, str]:
        path = f"/v1/agents/{agent_id}/runs"
        data = self._request("POST", path, key, {"prompt": {"text": prompt}})
        return _view(data, agent_id)

    def cancel(self, agent_id: str, run_id: str, key: str) -> None:
        self._request("POST", f"/v1/agents/{agent_id}/runs/{run_id}/cancel", key, {})

    def _request(
        self, method: str, path: str, key: str, body: dict[str, object] | None
    ) -> dict[str, object]:
        response = self._send(method, path, key, body)
        data = _json(response)
        if response.status_code == 409 or _exists(data):
            return {"error": "already exists"}
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CursorError(str(exc)) from exc
        return data

    def _text(self, method: str, path: str, key: str) -> str:
        response = self._send(method, path, key, None)
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CursorError(str(exc)) from exc
        return response.text

    def _send(
        self, method: str, path: str, key: str, body: dict[str, object] | None
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {key}"}
        try:
            with httpx.Client(base_url=self.base, transport=self.transport, timeout=30) as client:
                return client.request(method, path, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise CursorError(str(exc)) from exc


def _json(response: httpx.Response) -> dict[str, object]:
    try:
        loaded = response.json()
    except json.JSONDecodeError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {str(key): value for key, value in loaded.items()}


def _exists(data: dict[str, object]) -> bool:
    error = data.get("error", "")
    return "already exists" in str(error).casefold()


def _view(data: dict[str, object], agent_id: str) -> dict[str, str]:
    run = data.get("run_id", data.get("runId", ""))
    url = data.get("url", data.get("targetUrl", ""))
    status = data.get("status", "")
    text = data.get("text", "")
    return {
        "id": str(data.get("id", agent_id)),
        "run_id": str(run),
        "status": str(status),
        "text": str(text),
        "url": str(url),
    }


def _events(text: str) -> list[dict[str, str]]:
    if text.lstrip().startswith("["):
        return _array(text)
    found: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        found.extend(_array(raw) if raw.startswith("[") else _one(raw))
    return found


def _array(text: str) -> list[dict[str, str]]:
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    rows: list[dict[str, str]] = []
    for item in loaded:
        if isinstance(item, dict):
            rows.append({str(key): str(value) for key, value in item.items()})
    return rows


def _one(raw: str) -> list[dict[str, str]]:
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, dict):
        return []
    return [{str(key): str(value) for key, value in loaded.items()}]
