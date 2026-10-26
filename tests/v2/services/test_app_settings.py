"""Machine values live in the user config.yaml; API keys live in the keyring."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from iterthink.services import app_settings
from iterthink.services.bridge import Invalid


def test_machine_value_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    assert app_settings.value(path, "appearance") == ("light", "default")
    app_settings.set_value(path, "appearance", "dark")
    assert app_settings.value(path, "appearance") == ("dark", "machine")
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["appearance"] == "dark"
    app_settings.set_value(path, "privacy_shield_reinject", "off")
    assert app_settings.value(path, "privacy_shield_reinject") == (False, "machine")
    app_settings.clear_value(path, "appearance")
    assert app_settings.value(path, "appearance") == ("light", "default")


def test_a_copy_of_the_seed_counts_as_default(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text((app_settings.SEED).read_text(encoding="utf-8"), encoding="utf-8")
    assert app_settings.value(path, "token_cost_period") == ("year", "default")


def test_unknown_machine_key_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    with pytest.raises(Invalid, match="unknown setting"):
        app_settings.set_value(path, "rm_rf", "yes")
    with pytest.raises(Invalid, match="appearance"):
        app_settings.set_value(path, "appearance", "purple")


def test_machine_secret_goes_to_keyring_not_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored: list[tuple[str, str, str]] = []

    def remember(service: str, key: str, value: str) -> None:
        stored.append((service, key, value))

    monkeypatch.setattr(app_settings.keyring, "set_password", remember)
    path = tmp_path / "config.yaml"
    app_settings.set_value(path, "cloud_api_key", "sk-secret")
    assert stored == [("iterthink", "cloud_api_key", "sk-secret")]
    assert "sk-secret" not in path.read_text(encoding="utf-8")
    assert app_settings.value(path, "cloud_api_key") == ("stored", "machine")
