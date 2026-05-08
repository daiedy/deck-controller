"""Tests for backend.config — configuration management."""

from __future__ import annotations

import json

from backend.config import Config


class TestConfigLoadDefaults:
    def test_loads_builtin_defaults_when_no_files_exist(self, tmp_path):
        cfg = Config(
            config_path=str(tmp_path / "config.json"),
            defaults_path=str(tmp_path / "nonexistent_defaults.json"),
        )
        assert cfg.controller_name == "Deck Controller"
        assert cfg.auto_connect is False
        assert cfg.polling_rate_hz == 250
        assert cfg.deadzone == 0.05

    def test_loads_defaults_from_file(self, tmp_path, defaults_json):
        cfg = Config(
            config_path=str(tmp_path / "config.json"),
            defaults_path=defaults_json,
        )
        assert cfg.controller_name == "Deck Controller"
        assert cfg.bt_device_class == "0x002508"


class TestConfigMerge:
    def test_user_config_overrides_defaults(self, tmp_path, defaults_json):
        user_cfg = tmp_path / "config.json"
        user_cfg.write_text(json.dumps({"controller_name": "MyDeck", "deadzone": 0.1}))

        cfg = Config(config_path=str(user_cfg), defaults_path=defaults_json)
        assert cfg.controller_name == "MyDeck"
        assert cfg.deadzone == 0.1
        # Defaults are preserved for keys not overridden
        assert cfg.polling_rate_hz == 250

    def test_invalid_json_uses_defaults(self, tmp_path, defaults_json):
        bad = tmp_path / "config.json"
        bad.write_text("not json{{{")

        cfg = Config(config_path=str(bad), defaults_path=defaults_json)
        assert cfg.controller_name == "Deck Controller"


class TestConfigGetSet:
    def test_get_existing_key(self, tmp_path, defaults_json):
        cfg = Config(config_path=str(tmp_path / "c.json"), defaults_path=defaults_json)
        assert cfg.get("controller_name") == "Deck Controller"

    def test_get_missing_key_returns_default(self, tmp_path, defaults_json):
        cfg = Config(config_path=str(tmp_path / "c.json"), defaults_path=defaults_json)
        assert cfg.get("nonexistent", 42) == 42

    def test_set_persists_to_disk(self, tmp_path, defaults_json):
        cfg_path = str(tmp_path / "c.json")
        cfg = Config(config_path=cfg_path, defaults_path=defaults_json)
        cfg.set("controller_name", "Updated")

        # Re-read from disk
        with open(cfg_path) as f:
            data = json.load(f)
        assert data["controller_name"] == "Updated"

    def test_set_then_get(self, tmp_path, defaults_json):
        cfg = Config(config_path=str(tmp_path / "c.json"), defaults_path=defaults_json)
        cfg.set("deadzone", 0.2)
        assert cfg.get("deadzone") == 0.2


class TestConfigProperties:
    def test_property_getter(self, tmp_path, defaults_json):
        cfg = Config(config_path=str(tmp_path / "c.json"), defaults_path=defaults_json)
        assert cfg.enable_gyro is False
        assert cfg.max_connections == 1

    def test_property_setter(self, tmp_path, defaults_json):
        cfg = Config(config_path=str(tmp_path / "c.json"), defaults_path=defaults_json)
        cfg.controller_name = "NewName"
        assert cfg.controller_name == "NewName"

        cfg.auto_connect = True
        assert cfg.auto_connect is True

        cfg.polling_rate_hz = 500
        assert cfg.polling_rate_hz == 500

        cfg.enable_trackpads = True
        assert cfg.enable_trackpads is True

        cfg.bt_device_class = "0x123456"
        assert cfg.bt_device_class == "0x123456"

        cfg.max_connections = 3
        assert cfg.max_connections == 3


class TestConfigToDict:
    def test_returns_copy(self, tmp_path, defaults_json):
        cfg = Config(config_path=str(tmp_path / "c.json"), defaults_path=defaults_json)
        d = cfg.to_dict()
        d["controller_name"] = "MUTATED"
        assert cfg.controller_name == "Deck Controller"

    def test_contains_all_defaults(self, tmp_path, defaults_json):
        cfg = Config(config_path=str(tmp_path / "c.json"), defaults_path=defaults_json)
        d = cfg.to_dict()
        assert "controller_name" in d
        assert "deadzone" in d
        assert "polling_rate_hz" in d


class TestConfigSave:
    def test_creates_directory_if_needed(self, tmp_path, defaults_json):
        nested = tmp_path / "a" / "b" / "config.json"
        cfg = Config(config_path=str(nested), defaults_path=defaults_json)
        cfg.save()
        assert nested.exists()

    def test_roundtrip(self, tmp_path, defaults_json):
        cfg_path = str(tmp_path / "c.json")
        cfg = Config(config_path=cfg_path, defaults_path=defaults_json)
        cfg.set("deadzone", 0.15)

        cfg2 = Config(config_path=cfg_path, defaults_path=defaults_json)
        assert cfg2.deadzone == 0.15
