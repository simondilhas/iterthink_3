"""Machine values in the user config.yaml. API keys go to the keyring, never to YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import keyring
import yaml

from iterthink import config
from iterthink.ai.local_model import LINE_MODEL
from iterthink.services.bridge import Invalid

Source = Literal["default", "machine"]
SEED = Path(__file__).resolve().parents[1] / "defaults" / "config.yaml"
KEYRING_SERVICE = "iterthink"
_STORED = "stored_secrets"
_TRUE = {"1", "true", "yes", "on"}

# Keys the window offers, with the value used when neither file sets one.
MACHINE: dict[str, object] = {
    "ollama_host": "",
    "line_model": LINE_MODEL,
    "chat_model": "llama3:8B",
    "company_api_url": "",
    "company_model": "",
    "cloud_vendor": "openai",
    "cloud_model": "",
    "privacy_shield_company_enabled": True,
    "privacy_shield_cloud_enabled": True,
    "privacy_shield_reinject": True,
    "privacy_shield_show_masked_in_chat": False,
    "appearance": "light",
    "documents_root": "~/Documents/iterthink",
    "store_dir": "~/Documents/.iterthink",
    "token_cost_period": "year",
}
SECRETS = ("company_api_key", "cloud_api_key")
OPTIONS: dict[str, tuple[str, ...]] = {
    "appearance": ("light", "dark"),
    "cloud_vendor": ("openai", "anthropic", "google"),
    "token_cost_period": ("day", "month", "year"),
}
_SEED_NAMES = {"chat_model": "default_ollama_model"}


def _read(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def defaults() -> dict[str, object]:
    """Code defaults, overridden by the bundled seed where it has the key."""
    seed = _read(SEED)
    found = dict(MACHINE)
    for key in MACHINE:
        raw = seed.get(_SEED_NAMES.get(key, key))
        if raw is not None:
            found[key] = raw
    return found


def value(path: Path, key: str) -> tuple[object, Source]:
    """The effective value and whether the user's file changed it."""
    if key in SECRETS:
        stored = _read(path).get(_STORED)
        known = isinstance(stored, list) and key in stored
        return ("stored", "machine") if known else ("", "default")
    if key not in MACHINE:
        raise Invalid(f"unknown setting {key}")
    base = defaults()[key]
    user = _read(path)
    name = _SEED_NAMES.get(key, key)
    if name in user and user[name] is not None and user[name] != base:
        return user[name], "machine"
    return base, "default"


def set_value(path: Path, key: str, raw: object) -> object:
    """Write one machine value. Secrets go to the keyring and only a marker to YAML."""
    if key in SECRETS:
        return _set_secret(path, key, str(raw))
    if key not in MACHINE:
        raise Invalid(f"unknown setting {key}")
    coerced = _coerce(key, raw)
    data = _read(path)
    data[_SEED_NAMES.get(key, key)] = coerced
    _write(path, data)
    return coerced


def clear_value(path: Path, key: str) -> None:
    """Drop the user's value so the default applies again."""
    if key not in MACHINE:
        raise Invalid(f"unknown setting {key}")
    data = _read(path)
    if data.pop(_SEED_NAMES.get(key, key), None) is not None:
        _write(path, data)


def _set_secret(path: Path, key: str, raw: str) -> str:
    if not raw.strip():
        return "stored" if value(path, key)[0] == "stored" else ""
    keyring.set_password(KEYRING_SERVICE, key, raw.strip())
    data = _read(path)
    stored = data.get(_STORED)
    names = [item for item in stored if isinstance(item, str)] if isinstance(stored, list) else []
    if key not in names:
        names.append(key)
    data[_STORED] = names
    _write(path, data)
    return "stored"


def _coerce(key: str, raw: object) -> object:
    if isinstance(MACHINE[key], bool):
        return raw if isinstance(raw, bool) else str(raw).strip().casefold() in _TRUE
    text = str(raw).strip()
    allowed = OPTIONS.get(key)
    if allowed and text not in allowed:
        raise Invalid(f"{key} is one of {', '.join(allowed)}")
    if key in {"documents_root", "store_dir"} and not text:
        raise Invalid(f"{key} needs a folder")
    return text


def _write(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")
    if path.resolve() == config.APP_CONFIG_PATH.resolve():
        config.refresh()
