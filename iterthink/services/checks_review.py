"""Inherited checks as symbols next to a file. Advice only."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, cast

from iterthink.services.bridge import FileContent
from iterthink.services.egress import check
from iterthink.services.indexer import index_for
from iterthink.services.search import hybrid
from iterthink.services.settings import load_yaml

if TYPE_CHECKING:
    from iterthink.checks import Check


@dataclass(frozen=True)
class ListedCheck:
    id: str
    label: str


@dataclass(frozen=True)
class RegionMark:
    region: str
    symbol: str
    finding: str


@dataclass(frozen=True)
class CheckResult:
    path: str
    version: str
    check_id: str
    symbols: tuple[RegionMark, ...]
    sources: tuple[str, ...]
    cached: bool = False


class Model(Protocol):
    tier: str

    def complete(self, system: str, user: str, tier: str) -> str: ...


class _Host(Protocol):
    state_dir: Path

    def _root(self, project: str) -> Path: ...
    def _event(
        self, root: Path, project: str, actor: str, kind: str, payload: dict[str, object]
    ) -> None: ...
    def read(self, project: str, path: str) -> FileContent: ...


class _Chat:
    """Sync complete(), shaped like the check runner's chat client."""

    def __init__(self, model: Model, tier: str) -> None:
        self._model = model
        self._tier = tier

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        stream: bool,
        format: str,
    ) -> dict[str, dict[str, str]]:
        del model, stream, format
        text = self._model.complete(messages[0]["content"], messages[1]["content"], self._tier)
        return {"message": {"content": text}}


def _checks(root: Path) -> tuple[Check, ...]:
    from iterthink.checks import _parse_checks

    try:
        return _parse_checks(load_yaml(root, "checks.yaml"))
    except ValueError:
        return ()


def _find(root: Path, check_id: str) -> Check | None:
    for item in _checks(root):
        if item.id == check_id:
            return item
    return None


def _prompt_version(item: Check) -> str:
    raw = f"{item.system_prompt}\n{item.user_template}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


def _file_version(root: Path) -> str:
    from iterthink.persistence.snapshots import SnapshotError, Snapshots

    try:
        return Snapshots(root).head().id
    except SnapshotError:
        return "none"


def _cache_path(root: Path, version: str, prompt: str, check_id: str, path: str) -> Path:
    digest = hashlib.sha256(path.encode()).hexdigest()[:12]
    name = f"{version[:12]}-{prompt}-{check_id}-{digest}.json"
    return root / ".iterthink" / "checks" / name


def _marks(value: object) -> tuple[RegionMark, ...]:
    if not isinstance(value, list):
        return ()
    found: list[RegionMark] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        body = cast(dict[str, object], item)
        region = body.get("region")
        symbol = body.get("symbol")
        finding = body.get("finding")
        if isinstance(region, str) and isinstance(symbol, str) and isinstance(finding, str):
            found.append(RegionMark(region, symbol, finding))
    return tuple(found)


def _names(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _read_cache(
    root: Path, version: str, prompt: str, check_id: str, path: str
) -> CheckResult | None:
    file = _cache_path(root, version, prompt, check_id, path)
    if not file.is_file():
        return None
    try:
        loaded = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    body = cast(dict[str, object], loaded)
    marks = _marks(body.get("symbols"))
    return CheckResult(path, version, check_id, marks, _names(body.get("sources")), True)


def _write_cache(root: Path, result: CheckResult, prompt: str) -> None:
    file = _cache_path(root, result.version, prompt, result.check_id, result.path)
    file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "symbols": [
            {"region": mark.region, "symbol": mark.symbol, "finding": mark.finding}
            for mark in result.symbols
        ],
        "sources": list(result.sources),
    }
    file.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _sources(host: _Host, project: str, query: str) -> tuple[str, ...]:
    root = host._root(project)
    index = index_for(host.state_dir, project)
    index.update(root)
    seen: list[str] = []
    for hit in hybrid(index, project, query, 5):
        if hit.path not in seen:
            seen.append(hit.path)
    return tuple(seen)


def _regions(path: str, text: str | None) -> list[tuple[str, str]]:
    if not text or not text.strip():
        label = "page 1" if path.lower().endswith(".pdf") else "1"
        return [(label, "")]
    parts = [part.strip() for part in text.split("\n\n") if part.strip()]
    page = path.lower().endswith(".pdf")
    found: list[tuple[str, str]] = []
    for index, part in enumerate(parts, start=1):
        label = f"page {index}" if page else str(index)
        found.append((label, part))
    return found


def _ask(
    model: Model, item: Check, paragraph: str, context: str, tier: str
) -> dict[str, object] | None:
    from iterthink.services.checks_runner import run_paragraph

    payload, _error = asyncio.run(
        run_paragraph(
            _Chat(model, tier),
            model=tier,
            check=item,
            old="",
            new=paragraph,
            context=context,
        )
    )
    if not isinstance(payload, dict):
        return None
    return cast(dict[str, object], payload)


def _finding(item: Check, payload: dict[str, object]) -> str:
    from iterthink.checks import extract_summary

    raw = payload.get("finding")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return extract_summary(item, payload)


def _symbol(item: Check, payload: dict[str, object]) -> str:
    from iterthink.checks import extract_symbol

    return extract_symbol(item, payload)


def _mark(model: Model, item: Check, region: str, body: str, tier: str, context: str) -> RegionMark:
    if not body:
        return RegionMark(region, "?", "no text")
    payload = _ask(model, item, body, context, tier)
    if payload is None:
        return RegionMark(region, "?", "")
    return RegionMark(region, _symbol(item, payload), _finding(item, payload))


def _empty(path: str, version: str, check_id: str) -> CheckResult:
    return CheckResult(path, version, check_id, (), (), False)


class ChecksBridge:
    """Run checks.yaml on the open file. A symbol is not a verdict."""

    def use_checks_model(self, model: Model) -> None:
        self._checks_model = model

    def _checks_router(self) -> Model | None:
        found = getattr(self, "_checks_model", None)
        if found is None or not hasattr(found, "complete"):
            return None
        return cast(Model, found)

    def checks_for(self, project: str) -> list[ListedCheck]:
        host = cast(_Host, self)
        return [ListedCheck(item.id, item.label) for item in _checks(host._root(project))]

    def _checks_allowed(self, host: _Host, project: str) -> bool:
        model = self._checks_router()
        if model is None:
            return False
        tier = model.tier if model.tier in {"local", "company", "cloud"} else "local"
        named = cast(Literal["local", "company", "cloud"], tier)
        return check(host._root(project), "impact", named) != "deny"

    def run_check(
        self, project: str, path: str, check_id: str, actor: str = "user:local"
    ) -> CheckResult:
        host = cast(_Host, self)
        root = host._root(project)
        version = _file_version(root)
        chosen = _find(root, check_id)
        if chosen is None:
            return _empty(path, version, check_id)
        prompt = _prompt_version(chosen)
        stored = _read_cache(root, version, prompt, check_id, path)
        if stored is not None:
            return stored
        if not self._checks_allowed(host, project):
            return _empty(path, version, check_id)
        return self._fresh(host, project, root, path, actor, chosen, version, prompt)

    def _fresh(
        self,
        host: _Host,
        project: str,
        root: Path,
        path: str,
        actor: str,
        chosen: Check,
        version: str,
        prompt: str,
    ) -> CheckResult:
        model = self._checks_router()
        assert model is not None
        tier = model.tier if model.tier in {"local", "company", "cloud"} else "local"
        named = cast(Literal["local", "company", "cloud"], tier)
        content = host.read(project, path)
        text = content.text if isinstance(content.text, str) else None
        sources = _sources(host, project, text or path)
        context = ", ".join(sources)
        marks = tuple(
            _mark(model, chosen, region, body, named, context)
            for region, body in _regions(path, text)
        )
        result = CheckResult(path, version, chosen.id, marks, sources, False)
        _write_cache(root, result, prompt)
        host._event(
            root,
            project,
            actor,
            "check",
            {"check": chosen.id, "prompt_version": prompt, "model": named},
        )
        return result
