"""The Settings page on the real bridge: rows with their source, files, Ollama and the index."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, cast

import yaml

from iterthink.ai.local_model import LocalModel, connect, installed_models
from iterthink.services import app_settings, settings
from iterthink.services.bridge import Egress, Invalid, ProjectInfo, SettingInfo
from iterthink.services.indexer import index_for
from iterthink.services.projects import read_yaml
from iterthink.services.settings_sections import (
    FILES,
    LOCAL_MODEL_KEYS,
    SECTIONS,
    SPECS,
    OllamaStatus,
    Row,
    Section,
    Spec,
    installed,
    size,
)

_SHIELD = Path(__file__).resolve().parents[1] / "defaults" / "privacy_shield.yaml"
_EGRESS = {"none", "shielded", "allowed"}


class _Host(Protocol):
    state_dir: Path

    def _root(self, project: str) -> Path: ...
    def _event(
        self, root: Path, project: str, actor: str, kind: str, payload: dict[str, object]
    ) -> None: ...
    def files(self, project: str) -> list[Any]: ...
    def projects(self) -> list[ProjectInfo]: ...
    def set_egress(self, project: str, egress: Egress, actor: str) -> ProjectInfo: ...
    def pending_upgrades(self, project: str) -> list[dict[str, object]]: ...


def _categories() -> list[dict[str, object]]:
    found = read_yaml(_SHIELD).get("categories")
    rows: list[dict[str, object]] = []
    for item in found.values() if isinstance(found, dict) else []:
        if isinstance(item, dict):
            rows.append(
                {
                    "label": item.get("label", ""),
                    "mode": item.get("mode", ""),
                    "enabled": bool(item.get("enabled")),
                }
            )
    return rows


class SettingsWindowBridge:
    """Methods behind `/settings` and `/p/{id}/settings`."""

    _ollama_client: Any = None

    def _host(self) -> _Host:
        return cast(_Host, self)

    def _app_config(self) -> Path:
        return self._host().state_dir / "config.yaml"

    def _machine(self, key: str) -> object:
        return app_settings.value(self._app_config(), key)[0]

    def _default_workspace(self) -> Path:
        return Path(str(self._machine("documents_root"))).expanduser()

    def _scope(self, project: str | None) -> Path | None:
        return self._host()._root(project) if project else None

    def _inherited(self, root: Path | None) -> dict[str, SettingInfo]:
        found = (
            settings.all_settings(root)
            if root
            else settings.in_workspace(self._default_workspace())
        )
        return {item.key: item for item in found}

    def _row(
        self,
        spec: Spec,
        root: Path | None,
        inherited: dict[str, SettingInfo],
        saved: bool = False,
    ) -> Row:
        value, source = self._value(spec, root, inherited)
        if spec.control == "info":
            value = size(value)
        return Row(
            spec.key,
            spec.label,
            spec.control,
            spec.level,
            value,
            source,
            spec.group,
            spec.options,
            spec.note,
            saved,
        )

    def _value(
        self, spec: Spec, root: Path | None, inherited: dict[str, SettingInfo]
    ) -> tuple[object, str]:
        if spec.level == "machine":
            return app_settings.value(self._app_config(), spec.key)
        if spec.level == "egress" and root is not None:
            egress = read_yaml(root / ".iterthink" / "settings" / "project.yaml").get("egress")
            return (egress if egress in _EGRESS else "shielded"), "project"
        found = inherited.get(spec.key)
        return (found.value, found.source) if found else ("", "default")

    def settings_sections(self, project: str | None) -> list[Section]:
        root = self._scope(project)
        inherited = self._inherited(root)
        found: list[Section] = []
        for name, title, specs, project_only in SECTIONS:
            if project_only and root is None:
                continue
            rows = tuple(
                self._row(spec, root, inherited)
                for spec in specs
                if root is not None or not spec.project_only
            )
            found.append(Section(name, title, rows, self._extra(name, project)))
        return found

    def _extra(self, name: str, project: str | None) -> dict[str, object]:
        if name == "privacy":
            return {"categories": _categories()}
        if name == "prompts":
            level = "project" if project else "workspace"
            files = [(item, self.settings_file(project, item, level)) for item in FILES]
            asked = self._host().pending_upgrades(project) if project else []
            return {"files": files, "level": level, "questions": asked}
        if name == "index" and project:
            return {"index": self.index_status(project)}
        return {}

    def set_window_setting(
        self, project: str | None, key: str, value: str, level: str, actor: str
    ) -> Row:
        spec = self._spec(key)
        root = self._scope(project)
        if spec.level == "machine":
            app_settings.set_value(self._app_config(), key, value)
            if key in LOCAL_MODEL_KEYS:
                self._reconnect()
        elif spec.level == "egress":
            if not project or value not in _EGRESS:
                raise Invalid("egress is none, shielded or allowed, inside a project")
            self._host().set_egress(project, cast(Egress, value), actor)
        elif root is not None:
            settings.set_value(root, key, value, level, actor, self._host()._event)
        else:
            settings.set_in_workspace(self._default_workspace(), key, value)
        return self._row(spec, root, self._inherited(root), saved=True)

    def clear_window_setting(self, project: str | None, key: str, level: str, actor: str) -> Row:
        spec = self._spec(key)
        root = self._scope(project)
        if spec.level == "machine":
            app_settings.clear_value(self._app_config(), key)
            if key in LOCAL_MODEL_KEYS:
                self._reconnect()
        elif spec.level == "inherited" and root is not None:
            settings.clear_value(root, key, level, actor, self._host()._event)
        elif spec.level == "inherited":
            settings.clear_in_workspace(self._default_workspace(), key)
        return self._row(spec, root, self._inherited(root), saved=True)

    def _spec(self, key: str) -> Spec:
        spec = SPECS.get(key)
        if spec is None or spec.level == "info":
            raise Invalid(f"unknown setting {key}")
        return spec

    def use_local_model(self, warm: bool = True) -> None:
        """The line and chats use the local Ollama models chosen in Settings."""
        host = str(self._machine("ollama_host") or "") or None
        connect(
            self,
            line_model=str(self._machine("line_model")),
            chat_model=str(self._machine("chat_model")),
            host=host,
            client=self._ollama_client,
            warm=warm,
        )

    def _reconnect(self) -> None:
        if isinstance(getattr(self, "_intent_router", None), LocalModel):
            self.use_local_model()

    def ollama_status(self) -> OllamaStatus:
        host = str(self._machine("ollama_host") or "") or None
        models = installed_models(self._ollama_client, host)
        if models is None:
            return OllamaStatus(False, (), ())
        wanted = (str(self._machine("line_model")), str(self._machine("chat_model")))
        missing = tuple(name for name in dict.fromkeys(wanted) if not installed(models, name))
        return OllamaStatus(True, models, missing)

    def _settings_folder(self, project: str | None, level: str) -> Path:
        root = self._scope(project)
        if level == "project":
            if root is None:
                raise Invalid("project settings need a project")
            return root / ".iterthink" / "settings"
        if level != "workspace":
            raise Invalid("level is workspace or project")
        workspace = root.parent if root is not None else self._default_workspace()
        return workspace / ".iterthink" / "settings"

    def settings_file(self, project: str | None, name: str, level: str) -> str:
        """The file at that level, or the bundled default when there is none yet."""
        if name not in FILES:
            raise Invalid(f"unknown settings file {name}")
        own = self._settings_folder(project, level) / name
        source = own if own.is_file() else settings.SEEDS_DIR / name
        return source.read_text(encoding="utf-8")

    def save_settings_file(self, project: str | None, name: str, level: str, text: str) -> None:
        if name not in FILES:
            raise Invalid(f"unknown settings file {name}")
        try:
            loaded = yaml.safe_load(text)
        except yaml.YAMLError as error:
            raise Invalid(f"Not valid YAML: {error}") from error
        if not isinstance(loaded, dict):
            raise Invalid("Not valid YAML: the file must be a mapping")
        target = self._settings_folder(project, level) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text.replace("\r\n", "\n"), encoding="utf-8")

    def index_status(self, project: str) -> dict[str, object]:
        index = index_for(self._host().state_dir, project)
        try:
            row = index.conn.execute("SELECT count(*) FROM audit_events").fetchone()
            events = int(row[0]) if row else 0
            stored = index.db_path.stat().st_size if index.db_path.is_file() else 0
        finally:
            index.close()
        return {"events": events, "size": size(stored), "files": len(self._host().files(project))}

    def index_rebuild(self, project: str) -> dict[str, object]:
        index = index_for(self._host().state_dir, project)
        try:
            index.rebuild(self._host()._root(project))
        finally:
            index.close()
        return self.index_status(project)

    def appearance(self) -> str:
        return "dark" if self._machine("appearance") == "dark" else "light"

    def shortcut_keys(self, project: str | None) -> dict[str, str]:
        """Read on every page, so it never touches the storage trend."""
        root = self._scope(project)
        keys = [f"shortcuts.{name}" for name in ("line", "save", "files")]
        if root is None:
            found = {item.key: item for item in settings.in_workspace(self._default_workspace())}
        else:
            found = {key: settings.get(root, key) for key in keys}
        return {key.split(".", 1)[1]: str(found[key].value) for key in keys if key in found}
