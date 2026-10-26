"""Inherited settings. Defaults, then the workspace, then the project."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

import keyring
import yaml

from iterthink.services.bridge import Invalid, SettingInfo
from iterthink.services.projects import read_yaml, write_yaml

Level = Literal["workspace", "project"]
Source = Literal["default", "workspace", "project"]
Layer = tuple[object, Source]
Rows = list[dict[str, object]]
SEEDS_DIR = Path(__file__).resolve().parents[1] / "defaults"
_LEVELS = {"workspace", "project"}
_SECRET = ("secret", "api_key", "token", "password")

# Keys this slice shows. config.yaml supplies model.local when it has
# default_ollama_model; the rest are not in the seed and live here.
KEYS: dict[str, object] = {
    "model.local": "llama3:8B",
    "model.company": "",
    "model.cloud": "",
    "apps.builder_tier": "local",
    "runner.max_parallel": 1,
    "runner.max_parallel_local": 1,
    "runner.max_parallel_cloud": 4,
    "dictation.language": "auto",
    "dictation.model": "small",
    "dictation.hotkey": "Mod+Shift+Space",
    "dictation.hands_free": "off",
    "shortcuts.line": "Mod+K",
    "shortcuts.save": "Mod+S",
    "shortcuts.files": "Mod+E",
}


def get(project_dir: Path, key: str) -> SettingInfo:
    """The merged value and which layer it came from."""
    found = _merged(project_dir)
    if key not in found:
        raise Invalid(f"unknown setting {key}")
    value, source = found[key]
    return SettingInfo(key=key, value=value, source=source)


def all_settings(project_dir: Path) -> list[SettingInfo]:
    """Every known setting, then the storage sizes."""
    rows = [get(project_dir, key) for key in KEYS]
    sizes = storage(project_dir)
    rows.append(SettingInfo("storage.versions", sizes["versions"], "project"))
    rows.append(SettingInfo("storage.log", sizes["log"], "project"))
    rows.append(SettingInfo("storage.log_delta", sizes["log_delta"], "project"))
    return rows


def set_value(
    project_dir: Path,
    key: str,
    value: object,
    level: str,
    actor: str,
    emit: object,
) -> SettingInfo:
    """Write one override. A secret goes to the keyring, never to YAML."""
    if level not in _LEVELS:
        raise Invalid("level is workspace or project")
    if key not in KEYS and not _is_secret(key):
        raise Invalid(f"unknown setting {key}")
    previous = _current(project_dir, key)
    if _is_secret(key):
        keyring.set_password("iterthink", key, str(value))
        _emit(emit, project_dir, actor, key, previous, "stored", level)
        return SettingInfo(key=key, value="stored", source=cast(Level, level))
    stored = _coerce(key, value)
    data = read_yaml(_values_path(project_dir, cast(Level, level)))
    data[key] = stored
    write_yaml(_values_path(project_dir, cast(Level, level)), data)
    _emit(emit, project_dir, actor, key, previous, stored, level)
    return get(project_dir, key)


def load_yaml(project_dir: Path, name: str) -> dict[str, object]:
    """Bundled file, then workspace, then project. Lists and scalars replace."""
    if "/" in name or name.startswith("."):
        raise Invalid("settings file must be a single name")
    merged: dict[str, object] = {}
    for path in _chain(project_dir, name):
        merged = _merge(merged, _read_any(path))
    return merged


def upgrade(project_dir: Path) -> list[dict[str, object]]:
    """Merge new default keys. Ask when a default changed and the copy was edited."""
    questions: list[dict[str, object]] = []
    for path in sorted(SEEDS_DIR.glob("*.yaml")):
        questions.extend(_upgrade_one(project_dir, path.name, _read_any(path)))
    return questions


def resolve(project_dir: Path, name: str, key: str, choice: str) -> None:
    """keep mine, take the new default, or merge two mappings."""
    if choice not in {"keep", "take", "merge"}:
        raise Invalid("choose keep, take or merge")
    if "/" in name or name.startswith("."):
        raise Invalid("settings file must be a single name")
    bundled = _read_any(SEEDS_DIR / name)
    folder = project_dir / ".iterthink" / "settings"
    runtime = _read_any(folder / name)
    base = _read_any(folder / "_base" / name)
    new = bundled.get(key)
    current = runtime.get(key)
    if choice == "keep":
        base[key] = current
    elif choice == "merge" and isinstance(current, dict) and isinstance(new, dict):
        runtime[key] = _merge(current, new)
        base[key] = new
    else:
        runtime[key] = new
        base[key] = new
    write_yaml(folder / name, runtime)
    write_yaml(folder / "_base" / name, base)


def storage(project_dir: Path) -> dict[str, int]:
    """Bytes in versions and the log, and how much the log grew since last time."""
    versions = _bytes(project_dir / ".iterthink" / "versions")
    log = _bytes(project_dir / ".iterthink" / "log")
    seen = read_yaml(project_dir / ".iterthink" / "settings" / "storage.yaml")
    previous = seen.get("log")
    before = previous if isinstance(previous, int) else log
    write_yaml(
        project_dir / ".iterthink" / "settings" / "storage.yaml",
        {"versions": versions, "log": log},
    )
    return {"versions": versions, "log": log, "log_delta": log - before}


def _upgrade_one(project_dir: Path, name: str, bundled: dict[str, object]) -> Rows:
    runtime_path = project_dir / ".iterthink" / "settings" / name
    if not runtime_path.is_file():
        return []
    base_path = project_dir / ".iterthink" / "settings" / "_base" / name
    runtime = _read_any(runtime_path)
    base = _read_any(base_path)
    merged, nxt, questions = _reconcile(base, runtime, bundled, name)
    write_yaml(runtime_path, merged)
    write_yaml(base_path, nxt)
    return questions


def _reconcile(
    base: dict[str, object],
    runtime: dict[str, object],
    bundled: dict[str, object],
    name: str,
) -> tuple[dict[str, object], dict[str, object], Rows]:
    merged = dict(runtime)
    nxt = dict(base)
    questions: Rows = []
    for key, new in bundled.items():
        if key not in runtime:
            merged[key] = new
            nxt[key] = new
            continue
        current = runtime[key]
        if key not in base:
            if new != current:
                questions.append({"file": name, "key": key, "mine": current, "new": new})
            else:
                nxt[key] = new
            continue
        old = base[key]
        if current == old and new != current:
            merged[key] = new
            nxt[key] = new
        elif new != old and new != current:
            questions.append({"file": name, "key": key, "mine": current, "new": new})
            nxt[key] = old
        else:
            nxt[key] = new
    return merged, nxt, questions


def _merged(project_dir: Path) -> dict[str, Layer]:
    found: dict[str, Layer] = {}
    defaults = dict(KEYS)
    model = _read_any(SEEDS_DIR / "config.yaml").get("default_ollama_model")
    if isinstance(model, str) and model:
        defaults["model.local"] = model
    for key, value in defaults.items():
        found[key] = (value, "default")
    for source, path in (
        ("workspace", _workspace_values(project_dir)),
        ("project", project_dir / ".iterthink" / "settings" / "values.yaml"),
    ):
        for key, value in read_yaml(path).items():
            if key in KEYS:
                found[key] = (value, cast(Literal["workspace", "project"], source))
    return found


def _workspace_values(project_dir: Path) -> Path:
    folder = project_dir.parent / ".iterthink" / "settings"
    if not folder.is_dir():
        return folder / "values.yaml"
    return folder / "values.yaml"


def _values_path(project_dir: Path, level: Level) -> Path:
    if level == "workspace":
        return project_dir.parent / ".iterthink" / "settings" / "values.yaml"
    return project_dir / ".iterthink" / "settings" / "values.yaml"


def _chain(project_dir: Path, name: str) -> list[Path]:
    paths = [SEEDS_DIR / name]
    workspace = project_dir.parent / ".iterthink" / "settings"
    if workspace.is_dir():
        paths.append(workspace / name)
    paths.append(project_dir / ".iterthink" / "settings" / name)
    return paths


def _read_any(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _merge(base: dict[str, object], override: dict[str, object]) -> dict[str, object]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merge(current, value)
        else:
            merged[key] = value
    return merged


def _bytes(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    return sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())


def _current(project_dir: Path, key: str) -> object:
    if key in KEYS:
        return get(project_dir, key).value
    return None


def _coerce(key: str, value: object) -> object:
    if key.startswith("runner.max_parallel") and isinstance(value, str) and value.isdigit():
        return int(value)
    return value


def _is_secret(key: str) -> bool:
    folded = key.casefold()
    return any(part in folded for part in _SECRET)


class SettingsBridge:
    """Real-bridge methods. Kept here so bridge_real.py stays within the line limit."""

    def settings(self, project: str) -> list[SettingInfo]:
        return all_settings(_root_of(self, project))

    def set_setting(
        self, project: str, key: str, value: str, level: str, actor: str
    ) -> SettingInfo:
        root = _root_of(self, project)
        return set_value(root, key, value, level, actor, getattr(self, "_event", None))

    def pending_upgrades(self, project: str) -> Rows:
        return upgrade(_root_of(self, project))

    def resolve_upgrade(self, project: str, name: str, key: str, choice: str) -> None:
        resolve(_root_of(self, project), name, key, choice)


def _root_of(bridge: object, project: str) -> Path:
    root = getattr(bridge, "_root", None)
    if not callable(root):
        raise Invalid("settings need a project")
    found = root(project)
    if not isinstance(found, Path):
        raise Invalid("settings need a project")
    return found


def _emit(
    emit: object, project_dir: Path, actor: str, key: str, old: object, new: object, level: str
) -> None:
    if not callable(emit):
        return
    project = read_yaml(project_dir / ".iterthink" / "settings" / "project.yaml").get("id")
    emit(
        project_dir,
        project if isinstance(project, str) else "",
        actor,
        "settings",
        {"key": key, "old": old, "new": new, "level": level},
    )
