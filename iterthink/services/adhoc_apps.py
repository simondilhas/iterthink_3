"""Build, validate, keep and discard a small app. The model never sees file contents."""

from __future__ import annotations

import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Protocol, cast

from iterthink.services.app_calls import perform, stage_revision
from iterthink.services.app_context import prompt_version, system_prompt, tier_of, user_prompt
from iterthink.services.app_validate import ALLOWED, bridge_calls, parse_build, problems
from iterthink.services.bridge import (
    AppInfo,
    FileContent,
    FileDiff,
    FileEntry,
    Invalid,
    NotFound,
    ProposalInfo,
    SearchHit,
    VersionInfo,
)
from iterthink.services.projects import read_yaml, write_yaml

_EXAMPLES = Path(__file__).resolve().parents[1] / "defaults" / "app_examples"
_JS = Path(__file__).resolve().parents[1] / "web" / "static" / "js" / "app-bridge.js"
_STRING = re.compile(r"""['"]([^'"]+)['"]""")
_State = Literal["draft", "kept", "discarded"]


class Model(Protocol):
    def complete(self, system: str, user: str, tier: str) -> str: ...


class _Host(Protocol):
    machine: str

    def _root(self, project: str) -> Path: ...
    def _event(
        self, root: Path, project: str, actor: str, kind: str, payload: dict[str, object]
    ) -> None: ...
    def files(self, project: str) -> list[FileEntry]: ...
    def read(self, project: str, path: str) -> FileContent: ...
    def history(self, project: str, path: str | None = None) -> list[VersionInfo]: ...
    def search(self, project: str, query: str, limit: int = 50) -> list[SearchHit]: ...
    def diff(
        self, project: str, path: str, base: str | None = None, target: str | None = None
    ) -> FileDiff: ...
    def propose(
        self,
        project: str,
        changes: Mapping[str, str],
        actor: str,
        reason: str,
        baseline: str | None = None,
    ) -> ProposalInfo: ...


def build(host: _Host, project: str, line: str, actor: str) -> AppInfo:
    """Ask the builder up to three times, then store the app or say what failed."""
    model = _require_model(host)
    root = host._root(project)
    tier = tier_of(root)
    system = system_prompt()
    user = user_prompt(host, project, line, tier)
    errors = ["The builder did not answer."]
    previous = ""
    for attempt in range(1, 4):
        info, errors, previous = _once(
            host, project, actor, model, system, user, tier, line, attempt, errors, previous
        )
        if info is not None:
            return info
    _audit(host, root, project, actor, _body("build", "", line, tier, 3, " ".join(errors)))
    raise Invalid("The app could not be built after 3 attempts. " + " ".join(errors))


def keep(host: _Host, project: str, slug: str, actor: str) -> AppInfo:
    root = host._root(project)
    data = _mark(root, slug, "kept")
    _audit(host, root, project, actor, _body("keep", slug, "", tier_of(root), 0, "ok"))
    return _info(slug, data)


def discard(host: _Host, project: str, slug: str, actor: str) -> AppInfo:
    root = host._root(project)
    data = _mark(root, slug, "discarded")
    folder = _folder(root, slug)
    dest = _archive(root, slug)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(folder), str(dest))
    _audit(host, root, project, actor, _body("discard", slug, "", tier_of(root), 0, "ok"))
    return _info(slug, data)


def list_apps(root: Path) -> list[AppInfo]:
    folder = root / ".iterthink" / "apps"
    if not folder.is_dir():
        return []
    found: list[AppInfo] = []
    for child in sorted(path for path in folder.iterdir() if path.is_dir()):
        if child.name.startswith("."):
            continue
        data = read_yaml(child / "manifest.yaml")
        if data.get("hidden") is True or data.get("status") == "discarded":
            continue
        found.append(_info(child.name, data))
    return found


def srcdoc(root: Path, slug: str, origin: str) -> str:
    """The frame document: its own CSP, the bridge, then the app."""
    html = (_folder(root, slug) / "index.html").read_text(encoding="utf-8")
    script = _JS.read_text(encoding="utf-8") if _JS.is_file() else ""
    vendor = origin.rstrip("/")
    policy = (
        "default-src 'none'; "
        f"script-src 'unsafe-inline' {vendor}/static/vendor/; "
        "style-src 'unsafe-inline'; img-src data: blob:"
    )
    meta = f'<meta http-equiv="Content-Security-Policy" content="{policy}">'
    return f"{meta}<script>{script}</script>{html}"


def install(root: Path, slug: str) -> AppInfo:
    """Copy one shipped example into the project so it can be called."""
    source = _EXAMPLES / slug / "index.html"
    if not source.is_file():
        raise NotFound(f"no example {slug}")
    target = root / ".iterthink" / "apps" / slug
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    (target / "index.html").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    manifest = source.parent / "manifest.yaml"
    text = manifest.read_text(encoding="utf-8") if manifest.is_file() else ""
    (target / "manifest.yaml").write_text(text, encoding="utf-8")
    return _info(slug, read_yaml(target / "manifest.yaml"))


def close_app(root: Path, slug: str) -> AppInfo:
    """Hide a draft. A kept app stays listed."""
    folder = _folder(root, slug)
    data = read_yaml(folder / "manifest.yaml")
    if data.get("status") != "kept":
        data["hidden"] = True
        write_yaml(folder / "manifest.yaml", data)
    return _info(slug, data)


def revise(host: _Host, project: str, slug: str, instruction: str, actor: str) -> str:
    """A change to the app is a proposal. The current file stays until it is accepted."""
    model = _require_model(host)
    root = host._root(project)
    _folder(root, slug)
    tier = tier_of(root)
    current = (root / ".iterthink" / "apps" / slug / "index.html").read_text(encoding="utf-8")
    user = user_prompt(host, project, instruction, tier) + "\n\nCurrent app:\n" + current[:4000]
    parsed = parse_build(model.complete(system_prompt(), user, tier))
    if parsed is None:
        raise Invalid("The reply was not the JSON contract.")
    html = str(parsed["html"])
    extra = parsed.get("module")
    module = extra if isinstance(extra, str) else ""
    found = problems(html, module)
    if found:
        raise Invalid("The change was not valid. " + " ".join(found))
    return stage_revision(root, host.machine, project, slug, html, actor, instruction)


class AppsBridge:
    """Ad-hoc apps for one project. Delivery is srcdoc, not a second origin."""

    def use_app_model(self, model: Model) -> None:
        self._app_model = model

    def app_build(self, project: str, request: str, actor: str) -> AppInfo:
        return build(cast(_Host, self), project, request, actor)

    def app_run(self, project: str, app_id: str) -> AppInfo:
        root = cast(_Host, self)._root(project)
        return _info(app_id, read_yaml(_folder(root, app_id) / "manifest.yaml"))

    def app_keep(self, project: str, app_id: str, actor: str) -> AppInfo:
        return keep(cast(_Host, self), project, app_id, actor)

    def app_discard(self, project: str, app_id: str, actor: str) -> AppInfo:
        return discard(cast(_Host, self), project, app_id, actor)

    def apps(self, project: str) -> list[AppInfo]:
        return list_apps(cast(_Host, self)._root(project))

    def app_call(self, project: str, app_id: str, name: str, args: object, actor: str) -> object:
        host = cast(_Host, self)
        _folder(host._root(project), app_id)
        return perform(host, project, name, args, actor, dry=False)

    def app_srcdoc(self, project: str, app_id: str, origin: str) -> str:
        return srcdoc(cast(_Host, self)._root(project), app_id, origin)

    def install_example(self, project: str, slug: str) -> AppInfo:
        return install(cast(_Host, self)._root(project), slug)

    def app_close(self, project: str, app_id: str) -> AppInfo:
        return close_app(cast(_Host, self)._root(project), app_id)

    def app_revise(self, project: str, app_id: str, instruction: str, actor: str) -> str:
        return revise(cast(_Host, self), project, app_id, instruction, actor)


def _once(
    host: _Host,
    project: str,
    actor: str,
    model: Model,
    system: str,
    user: str,
    tier: str,
    line: str,
    attempt: int,
    errors: list[str],
    previous: str,
) -> tuple[AppInfo | None, list[str], str]:
    prompt = (
        user
        if not previous
        else f"{user}\n\nPrevious attempt failed:\n{previous}\n" + "\n".join(errors)
    )
    try:
        raw = model.complete(system, prompt, tier)
    except Exception:
        return None, ["The builder did not answer."], previous
    parsed = parse_build(raw)
    if parsed is None:
        return None, ["The reply was not the JSON contract."], raw[:400]
    html = str(parsed["html"])
    module = parsed.get("module")
    extra = module if isinstance(module, str) else ""
    found = problems(html, extra) or _dry(host, project, html + extra, actor)
    if found:
        return None, found, raw[:400]
    info = _store(host._root(project), parsed, html, extra, actor, tier, attempt)
    _audit(
        host,
        host._root(project),
        project,
        actor,
        _body("build", info.id, line, tier, attempt, "ok"),
    )
    return info, [], raw


def _dry(host: _Host, project: str, source: str, actor: str) -> list[str]:
    errors: list[str] = []
    for name, raw in bridge_calls(source):
        if name not in ALLOWED or name == "propose":
            continue
        arg = _STRING.search(raw)
        text = arg.group(1) if arg else ""
        result = perform(host, project, name, {"path": text, "query": text}, actor, dry=True)
        if isinstance(result, dict) and result.get("error"):
            errors.append(str(result["error"]))
    return errors


def _store(
    root: Path,
    parsed: dict[str, object],
    html: str,
    module: str,
    actor: str,
    tier: str,
    attempts: int,
) -> AppInfo:
    slug = _slug(str(parsed["slug"])) or "app"
    title = str(parsed["title"])
    purpose = str(parsed["purpose"])
    folder = _place(root, slug)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text(html, encoding="utf-8")
    if module:
        (folder / "module.js").write_text(module, encoding="utf-8")
    data: dict[str, object] = {
        "purpose": purpose,
        "inputs": _strings(parsed.get("inputs")),
        "created_by": actor,
        "model": tier,
        "prompt_version": prompt_version(),
        "attempts": attempts,
        "status": "draft",
        "title": title,
        "hidden": False,
    }
    write_yaml(folder / "manifest.yaml", data)
    return _info(folder.name, data)


def _require_model(host: object) -> Model:
    found = getattr(host, "_app_model", None)
    if found is None or not callable(getattr(found, "complete", None)):
        raise Invalid("no builder model")
    return cast(Model, found)


def _audit(host: _Host, root: Path, project: str, actor: str, payload: dict[str, object]) -> None:
    host._event(root, project, actor, "app", payload)


def _body(
    action: str, slug: str, line: str, tier: str, attempts: int, validation: str
) -> dict[str, object]:
    return {
        "action": action,
        "slug": slug,
        "line": line,
        "prompt": prompt_version(),
        "model": tier,
        "attempts": attempts,
        "validation": validation[:500],
    }


def _mark(root: Path, slug: str, status: str) -> dict[str, object]:
    folder = _folder(root, slug)
    data = read_yaml(folder / "manifest.yaml")
    data["status"] = status
    data["hidden"] = False
    write_yaml(folder / "manifest.yaml", data)
    return data


def _folder(root: Path, slug: str) -> Path:
    folder = root / ".iterthink" / "apps" / slug
    if not (folder / "index.html").is_file():
        raise NotFound(f"no app {slug}")
    return folder


def _place(root: Path, slug: str) -> Path:
    base = root / ".iterthink" / "apps"
    if not (base / slug).exists():
        return base / slug
    number = 2
    while (base / f"{slug}-{number}").exists():
        number += 1
    return base / f"{slug}-{number}"


def _archive(root: Path, slug: str) -> Path:
    base = root / ".iterthink" / "apps" / ".archive"
    if not (base / slug).exists():
        return base / slug
    number = 2
    while (base / f"{slug}-{number}").exists():
        number += 1
    return base / f"{slug}-{number}"


def _info(slug: str, data: dict[str, object]) -> AppInfo:
    title = data.get("title")
    return AppInfo(
        id=slug,
        title=title if isinstance(title, str) and title else slug,
        status=_literal(data.get("status")),
        url=None,
    )


def _literal(label: object) -> _State:
    if label == "kept":
        return "kept"
    if label == "discarded":
        return "discarded"
    return "draft"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:40]


def _strings(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
