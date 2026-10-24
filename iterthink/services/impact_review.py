"""Impact advice for one proposal. It lists files. It does not decide."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast

import yaml

from iterthink.services.egress import check
from iterthink.services.indexer import index_for
from iterthink.services.search import hybrid

_SEED = Path(__file__).resolve().parents[1] / "defaults" / "impact_checks.yaml"
_TEXT = (".md", ".csv")


@dataclass(frozen=True)
class ImpactAdvice:
    proposal: str
    suggestion: str
    affected: tuple[str, ...]
    confidence: float
    sources: tuple[str, ...]
    cached: bool = False


class Model(Protocol):
    tier: str

    def complete(self, system: str, user: str, tier: str) -> str: ...


class _Host(Protocol):
    state_dir: Path

    def _root(self, project: str) -> Path: ...
    def proposals(self, project: str, status: object = None) -> list[object]: ...


def check_version() -> str:
    """Short id of the seeded checks. The cache key changes when they change."""
    return hashlib.sha256(_SEED.read_bytes()).hexdigest()[:12]


def text_targets(paths: tuple[str, ...] | list[str]) -> bool:
    """Working text files are what the seeded checks read."""
    return any(path.endswith(_TEXT) for path in paths)


def _prompt() -> tuple[str, str]:
    loaded = yaml.safe_load(_SEED.read_text(encoding="utf-8"))
    items = loaded.get("impact_checks") if isinstance(loaded, dict) else None
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return "impact", ""
    first = cast(dict[str, object], items[0])
    ident = first.get("id")
    system = first.get("system_prompt")
    name = ident if isinstance(ident, str) else "impact"
    text = system if isinstance(system, str) else ""
    return name, text


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def _names(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _parse(text: str) -> tuple[str, tuple[str, ...], float]:
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return "not sure", (), 0.0
    if not isinstance(loaded, dict):
        return "not sure", (), 0.0
    body = cast(dict[str, object], loaded)
    suggestion = body.get("suggestion")
    label = suggestion if isinstance(suggestion, str) and suggestion else "not sure"
    return label, _names(body.get("affected")), _number(body.get("confidence"))


def _cache_file(root: Path, proposal: str, version: str) -> Path:
    return root / ".iterthink" / "impact" / f"{proposal}-{version}.json"


def _read_cache(root: Path, proposal: str, version: str) -> ImpactAdvice | None:
    path = _cache_file(root, proposal, version)
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    body = cast(dict[str, object], loaded)
    suggestion = body.get("suggestion")
    label = suggestion if isinstance(suggestion, str) else ""
    return ImpactAdvice(
        proposal,
        label,
        _names(body.get("affected")),
        _number(body.get("confidence")),
        _names(body.get("sources")),
        True,
    )


def _write_cache(root: Path, advice: ImpactAdvice, version: str) -> None:
    path = _cache_file(root, advice.proposal, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "suggestion": advice.suggestion,
        "affected": list(advice.affected),
        "confidence": f"{advice.confidence:.2f}",
        "sources": list(advice.sources),
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _sources(host: _Host, project: str, query: str) -> tuple[str, ...]:
    root = host._root(project)
    index = index_for(host.state_dir, project)
    index.update(root)
    found = hybrid(index, project, query, 5)
    seen: list[str] = []
    for hit in found:
        if hit.path not in seen:
            seen.append(hit.path)
    return tuple(seen)


def _proposal(host: _Host, project: str, proposal_id: str) -> object:
    for item in host.proposals(project, status=None):
        if getattr(item, "id", None) == proposal_id:
            return item
    raise KeyError(proposal_id)


class ImpactBridge:
    """A proposal can ask what else it touches. The answer is not a verdict."""

    def use_impact_model(self, model: Model) -> None:
        self._impact_model = model

    def _impact_router(self) -> Model | None:
        found = getattr(self, "_impact_model", None)
        if found is None or not hasattr(found, "complete"):
            return None
        return cast(Model, found)

    def impact_auto(self, project: str, proposal_id: str) -> bool:
        host = cast(_Host, self)
        try:
            item = _proposal(host, project, proposal_id)
        except KeyError:
            return False
        paths = getattr(item, "paths", ())
        return text_targets(paths if isinstance(paths, tuple) else ())

    def _impact_allowed(self, host: _Host, project: str) -> bool:
        model = self._impact_router()
        if model is None:
            return False
        tier = model.tier if model.tier in {"local", "company", "cloud"} else "local"
        named = cast(Literal["local", "company", "cloud"], tier)
        return check(host._root(project), "impact", named) != "deny"

    def impact_advice(
        self, project: str, proposal_id: str, actor: str = "user:local"
    ) -> ImpactAdvice:
        host = cast(_Host, self)
        _proposal(host, project, proposal_id)
        root = host._root(project)
        version = check_version()
        stored = _read_cache(root, proposal_id, version)
        if stored is not None:
            return stored
        if not self._impact_allowed(host, project):
            return ImpactAdvice(proposal_id, "not run", (), 0.0, ())
        model = self._impact_router()
        assert model is not None
        item = _proposal(host, project, proposal_id)
        paths = getattr(item, "paths", ())
        reason = getattr(item, "reason", "")
        query = " ".join(paths) if isinstance(paths, tuple) else ""
        if isinstance(reason, str) and reason:
            query = f"{reason} {query}".strip()
        sources = _sources(host, project, query) if query else ()
        check_id, system = _prompt()
        user = f"asked by {actor}\nproposal {proposal_id}\n{query}\ncontext: {', '.join(sources)}"
        tier = "local" if model.tier == "local" else model.tier
        raw = model.complete(f"{check_id}\n{system}", user, tier)
        suggestion, affected, confidence = _parse(raw)
        advice = ImpactAdvice(proposal_id, suggestion, affected, confidence, sources, False)
        _write_cache(root, advice, version)
        return advice
