"""Known workspaces, the default folder, and the explorer's project list."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from iterthink import config
from iterthink.services.bridge import (
    FolderInfo,
    Forbidden,
    Invalid,
    NotFound,
    ProjectInfo,
    ProposalInfo,
    ProposalStatus,
)
from iterthink.services.projects import (
    ensure_project,
    folder_entries,
    hide_iterthink,
    read_yaml,
    settings_of,
    write_yaml,
)

_FORBIDDEN = re.compile(r'[\x00-\x1f/\\:*?"<>|]')


@dataclass(frozen=True)
class WorkspaceItem:
    path: str
    name: str
    project_id: str | None
    proposals: int
    prompt: bool
    untracked: bool


@dataclass(frozen=True)
class ExplorerPanel:
    root: str
    projects: tuple[WorkspaceItem, ...]
    pending: tuple[WorkspaceItem, ...]
    loose: tuple[WorkspaceItem, ...]


@dataclass
class _Store:
    paths: list[str]
    seen: dict[str, list[str]]


class _Registry(Protocol):
    opened: list[tuple[str, Path]]

    def path_of(self, project: str) -> Path | None: ...


class _Host(Protocol):
    state_dir: Path
    _registry: _Registry

    def _adopt(self, folder: Path, project: str) -> str: ...
    def _scan_one(self, folder: Path, project: str) -> None: ...
    def _check(self, folder: Path, project: str, *, background: bool = False) -> str: ...
    def _event(
        self, root: Path, project: str, actor: str, kind: str, payload: dict[str, object]
    ) -> None: ...
    def _info(self, folder: Path) -> ProjectInfo: ...
    def _root(self, project: str) -> Path: ...
    def proposals(
        self, project: str, status: ProposalStatus | None = "open"
    ) -> list[ProposalInfo]: ...


def _key(folder: Path) -> str:
    return str(folder.expanduser().resolve())


def _file(state_dir: Path) -> Path:
    return state_dir / "workspaces.json"


def _load(state_dir: Path) -> _Store:
    path = _file(state_dir)
    if not path.is_file():
        return _Store([], {})
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _Store([], {})
    if not isinstance(raw, dict):
        return _Store([], {})
    paths = raw.get("paths")
    seen = raw.get("seen")
    kept = [item for item in paths if isinstance(item, str)] if isinstance(paths, list) else []
    return _Store(kept, _seen(seen))


def _seen(raw: object) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}
    found: dict[str, list[str]] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, list):
            found[key] = [item for item in value if isinstance(item, str)]
    return found


def _save(state_dir: Path, store: _Store) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = {"paths": store.paths, "seen": store.seen}
    _file(state_dir).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _remember(state_dir: Path, folder: Path) -> None:
    store = _load(state_dir)
    key = _key(folder)
    if key in store.paths:
        return
    store.paths.append(key)
    _save(state_dir, store)


def _known(state_dir: Path, folder: Path) -> bool:
    return _key(folder) in _load(state_dir).paths


def default_workspace(state_dir: Path) -> Path:
    """`documents_root`, created on first use and listed first."""
    root = config.DOCUMENTS.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    store = _load(state_dir)
    key = str(root)
    store.paths = [key, *[item for item in store.paths if item != key]]
    _save(state_dir, store)
    return root


def known_workspaces(state_dir: Path) -> list[Path]:
    return [Path(item) for item in _load(state_dir).paths]


def _project_id(folder: Path) -> str | None:
    found = settings_of(folder).get("id")
    if isinstance(found, str) and found:
        return found
    return None


def note_opened(state_dir: Path, folder: Path) -> None:
    """A folder of subfolders and no `.iterthink/` becomes a known workspace."""
    folder = folder.expanduser().resolve()
    if not folder.is_dir() or (folder / ".iterthink").exists() or _project_id(folder):
        return
    children = [
        item for item in folder.iterdir() if item.is_dir() and not item.name.startswith(".")
    ]
    if children:
        _remember(state_dir, folder)


def clean_name(name: str) -> str:
    """The typed name with characters a folder cannot keep removed."""
    cleaned = _FORBIDDEN.sub("", name).strip()
    if cleaned in {"", ".", ".."}:
        raise Invalid("name the project")
    return cleaned


def new_project_dir(state_dir: Path, name: str) -> Path:
    """A new folder in the default workspace. An existing folder is left untouched."""
    stem = clean_name(name)
    root = default_workspace(state_dir)
    chosen = root / stem
    number = 2
    while chosen.exists():
        chosen = root / f"{stem} {number}"
        number += 1
    chosen.mkdir()
    return chosen


def ignored_names(workspace: Path) -> list[str]:
    data = read_yaml(workspace / ".iterthink" / "settings" / "ignore.yaml")
    raw = data.get("ignore")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str)]


def add_ignore(workspace: Path, name: str) -> None:
    names = ignored_names(workspace)
    if name not in names:
        names.append(name)
    payload: dict[str, object] = {"ignore": names}
    write_yaml(workspace / ".iterthink" / "settings" / "ignore.yaml", payload)
    hide_iterthink(workspace)


def _children(folder: Path, ignored: set[str]) -> list[Path]:
    found = [
        child
        for child in folder.iterdir()
        if not child.name.startswith(".")
        and child.name not in ignored
        and (child.is_dir() or child.is_file())
    ]
    return sorted(found, key=lambda child: child.name.casefold())


def _fresh(state_dir: Path, folder: Path, names: list[str]) -> set[str]:
    """Names that appeared after the first time this workspace was listed."""
    store = _load(state_dir)
    key = _key(folder)
    previous = store.seen.get(key)
    fresh = set() if previous is None else set(names) - set(previous)
    store.seen[key] = sorted(names)
    _save(state_dir, store)
    return fresh


def _open_count(host: _Host, folder: Path, project: str) -> int:
    host._adopt(folder, project)
    return len(host.proposals(project, "open"))


def _one(host: _Host, child: Path, fresh: set[str]) -> WorkspaceItem:
    if not child.is_dir():
        return WorkspaceItem(str(child), child.name, None, 0, False, True)
    project = _project_id(child)
    count = _open_count(host, child, project) if project else 0
    return WorkspaceItem(
        str(child), child.name, project, count, project is None and child.name in fresh, False
    )


def workspace_items(host: _Host, folder: Path) -> list[WorkspaceItem]:
    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        raise NotFound(f"no folder at {folder}")
    children = _children(folder, set(ignored_names(folder)))
    names = [child.name for child in children if child.is_dir()]
    fresh = _fresh(host.state_dir, folder, names)
    return [_one(host, child, fresh) for child in children]


def _opened_projects(host: _Host) -> list[WorkspaceItem]:
    items: list[WorkspaceItem] = []
    for project, folder in host._registry.opened:
        if folder.is_dir():
            count = _open_count(host, folder, project)
            items.append(WorkspaceItem(str(folder), folder.name, project, count, False, False))
    return items


def _panel(host: _Host, items: list[WorkspaceItem], root: str) -> ExplorerPanel:
    projects = tuple(item for item in items if item.project_id)
    pending = tuple(item for item in items if item.project_id is None and not item.untracked)
    loose = tuple(item for item in items if item.untracked)
    return ExplorerPanel(root, projects, pending, loose)


def _track(host: _Host, folder: Path) -> ProjectInfo:
    folder = folder.expanduser().resolve()
    project, version = ensure_project(folder)
    if version is not None:
        host._event(
            folder,
            project,
            "user:local",
            "project_created",
            {"name": folder.name, "version": version},
        )
    if host._adopt(folder, project) == "copy":
        return _copied(host, folder, project)
    host._scan_one(folder, project)
    return host._info(folder)


def _copied(host: _Host, folder: Path, project: str) -> ProjectInfo:
    kept = host._registry.path_of(project)
    target = kept if kept is not None else folder
    host._scan_one(target, project)
    return host._info(target)


def _check_ignore(name: str) -> None:
    if not name or name in {".", ".."} or "/" in name or "\\" in name or name.startswith("."):
        raise Invalid("ignore one name")


def _as_host(bridge: WorkspacesBridge) -> _Host:
    return cast(_Host, bridge)


class WorkspacesBridge:
    """Workspace listing and where a relative new project is created."""

    def open_folder(self, path: Path) -> list[FolderInfo]:
        host = _as_host(self)
        note_opened(host.state_dir, path)
        found: list[FolderInfo] = []
        for folder, project in folder_entries(path):
            if project:
                host._adopt(folder, project)
                host._scan_one(folder, project)
                host._check(folder, project, background=True)
            found.append(FolderInfo(path=str(folder), name=folder.name, project_id=project))
        return found

    def make_project(self, path: Path) -> ProjectInfo:
        host = _as_host(self)
        expanded = path.expanduser()
        if not expanded.is_absolute():
            expanded = new_project_dir(host.state_dir, path.as_posix())
        return _track(host, expanded)

    def workspace_view(self, path: Path) -> list[WorkspaceItem]:
        host = _as_host(self)
        note_opened(host.state_dir, path)
        return workspace_items(host, path)

    def workspaces(self) -> list[Path]:
        return known_workspaces(_as_host(self).state_dir)

    def default_workspace(self) -> Path:
        return default_workspace(_as_host(self).state_dir)

    def workspace_ignore(self, workspace: Path, name: str) -> None:
        host = _as_host(self)
        folder = workspace.expanduser().resolve()
        if not _known(host.state_dir, folder):
            raise Forbidden("not a workspace")
        _check_ignore(name)
        add_ignore(folder, name)

    def explorer_panel(self, project: str) -> ExplorerPanel:
        host = _as_host(self)
        parent = host._root(project).parent
        note_opened(host.state_dir, parent)
        if _known(host.state_dir, parent):
            return _panel(host, workspace_items(host, parent), _key(parent))
        return _panel(host, _opened_projects(host), "")
