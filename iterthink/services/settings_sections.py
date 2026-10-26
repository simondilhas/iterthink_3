"""What the Settings page shows, section by section."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Control = Literal["text", "number", "select", "switch", "model", "secret", "folder", "info"]
Level = Literal["machine", "inherited", "egress", "info"]
Options = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Spec:
    key: str
    label: str
    control: Control
    level: Level
    group: str = ""
    options: Options = ()
    note: str = ""
    project_only: bool = False


@dataclass(frozen=True)
class Row:
    key: str
    label: str
    control: Control
    level: Level
    value: object
    source: str
    group: str = ""
    options: Options = ()
    note: str = ""
    saved: bool = False

    @property
    def overridden(self) -> bool:
        return self.level in {"machine", "inherited"} and self.source != "default"


@dataclass(frozen=True)
class Section:
    name: str
    title: str
    rows: tuple[Row, ...]
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class OllamaStatus:
    running: bool
    models: tuple[str, ...]
    missing: tuple[str, ...]


def _same(values: tuple[str, ...]) -> Options:
    return tuple((value, value) for value in values)


_TIERS = _same(("local", "company", "cloud"))
_MODELS = (
    Spec("ollama_host", "Ollama host", "text", "machine", note="Empty: this machine"),
    Spec("line_model", "Line model", "model", "machine"),
    Spec("chat_model", "Chat model", "model", "machine"),
    Spec("company_api_url", "API URL", "text", "machine", "Company"),
    Spec("company_model", "Model", "text", "machine", "Company"),
    Spec("company_api_key", "API key", "secret", "machine", "Company"),
    Spec(
        "cloud_vendor",
        "Vendor",
        "select",
        "machine",
        "Cloud",
        (("openai", "OpenAI"), ("anthropic", "Anthropic"), ("google", "Google")),
    ),
    Spec("cloud_model", "Model", "text", "machine", "Cloud"),
    Spec("cloud_api_key", "API key", "secret", "machine", "Cloud"),
    Spec("model.local", "Local model", "text", "inherited", "Apps and agents"),
    Spec("model.company", "Company model", "text", "inherited", "Apps and agents"),
    Spec("model.cloud", "Cloud model", "text", "inherited", "Apps and agents"),
    Spec("apps.builder_tier", "App builder", "select", "inherited", "Apps and agents", _TIERS),
    Spec("runner.max_parallel", "Tasks at once", "number", "inherited", "Apps and agents"),
    Spec(
        "runner.max_parallel_local", "Local tasks at once", "number", "inherited", "Apps and agents"
    ),
    Spec(
        "runner.max_parallel_cloud", "Cloud tasks at once", "number", "inherited", "Apps and agents"
    ),
)
_PRIVACY = (
    Spec(
        "egress",
        "Content may leave this machine",
        "select",
        "egress",
        options=(
            ("none", "only on this machine"),
            ("shielded", "redacted"),
            ("allowed", "allowed"),
        ),
        project_only=True,
    ),
    Spec("privacy_shield_company_enabled", "Shield company calls", "switch", "machine"),
    Spec("privacy_shield_cloud_enabled", "Shield cloud calls", "switch", "machine"),
    Spec("privacy_shield_reinject", "Restore original values in answers", "switch", "machine"),
    Spec("privacy_shield_show_masked_in_chat", "Show masked text in chat", "switch", "machine"),
)
_APPEARANCE = (
    Spec(
        "appearance",
        "Appearance",
        "select",
        "machine",
        options=(("light", "Light"), ("dark", "Dark")),
    ),
)
_PATHS = (
    Spec("documents_root", "Default workspace", "folder", "machine", note="New projects go here"),
    Spec("store_dir", "Store folder", "folder", "machine", note="Restart to apply"),
)
_DICTATION = (
    Spec(
        "dictation.language",
        "Language",
        "select",
        "inherited",
        options=(
            ("auto", "Automatic"),
            ("de", "German"),
            ("en", "English"),
            ("fr", "French"),
            ("it", "Italian"),
        ),
    ),
    Spec(
        "dictation.model",
        "Model size",
        "select",
        "inherited",
        options=_same(("tiny", "base", "small", "medium", "large-v3")),
    ),
    Spec("dictation.hotkey", "Hold to talk", "text", "inherited"),
    Spec("dictation.hands_free", "Hands-free", "select", "inherited", options=_same(("off", "on"))),
)
_STORAGE = (
    Spec("storage.versions", "Versions", "info", "info", project_only=True),
    Spec("storage.log", "Log", "info", "info", project_only=True),
    Spec("storage.log_delta", "Log growth since last look", "info", "info", project_only=True),
    Spec(
        "token_cost_period",
        "Usage period",
        "select",
        "machine",
        options=(("day", "Day"), ("month", "Month"), ("year", "Year")),
    ),
)
_SHORTCUTS = (
    Spec("shortcuts.line", "Recall the line", "text", "inherited"),
    Spec("shortcuts.save", "Save", "text", "inherited"),
    Spec("shortcuts.files", "Files", "text", "inherited"),
)

# name, title, rows, shown only inside a project
SECTIONS: tuple[tuple[str, str, tuple[Spec, ...], bool], ...] = (
    ("models", "Models", _MODELS, False),
    ("privacy", "Privacy", _PRIVACY, False),
    ("appearance", "Appearance", _APPEARANCE, False),
    ("paths", "Paths", _PATHS, False),
    ("dictation", "Dictation", _DICTATION, False),
    ("prompts", "Prompts and checks", (), False),
    ("index", "Search index", (), True),
    ("storage", "Storage and usage", _STORAGE, False),
    ("shortcuts", "Shortcuts", _SHORTCUTS, False),
)
SPECS: dict[str, Spec] = {spec.key: spec for _, _, specs, _ in SECTIONS for spec in specs}
FILES = ("prompts.yaml", "checks.yaml", "impact_checks.yaml", "rules.yaml", "agents.yaml")
LOCAL_MODEL_KEYS = {"line_model", "chat_model", "ollama_host"}


def installed(models: tuple[str, ...], wanted: str) -> bool:
    """Ollama names ignore case, and a name without a tag means `:latest`."""
    folded = wanted.strip().casefold()
    if not folded:
        return True
    names = {name.casefold() for name in models}
    return folded in names or f"{folded}:latest" in names


def size(count: object) -> str:
    amount = float(count) if isinstance(count, int | float) else 0.0
    for unit in ("B", "KB", "MB", "GB"):
        if abs(amount) < 1024 or unit == "GB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} GB"
