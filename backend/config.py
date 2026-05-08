"""Configuration management for Deck Controller plugin."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH: str = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "defaults",
    "defaults.json",
)

SETTINGS_DIR: str = os.environ.get(
    "DECKY_PLUGIN_SETTINGS_DIR",
    os.path.expanduser("~/homebrew/settings/deck-controller"),
)

CONFIG_FILE: str = os.path.join(SETTINGS_DIR, "config.json")


class Config:
    """Thread-safe configuration manager.

    Loads config from the plugin settings directory, merging with defaults.
    All property access is protected by a threading lock.
    """

    def __init__(self, config_path: str | None = None, defaults_path: str | None = None) -> None:
        self._lock = threading.Lock()
        self._config_path = config_path or CONFIG_FILE
        self._defaults_path = defaults_path or DEFAULT_CONFIG_PATH
        self._data: dict[str, Any] = {}
        self._load()

    def _load_defaults(self) -> dict[str, Any]:
        """Load default configuration values."""
        try:
            with open(self._defaults_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "controller_name": "Deck Controller",
                "auto_connect": False,
                "polling_rate_hz": 250,
                "deadzone": 0.05,
                "enable_gyro": False,
                "enable_trackpads": False,
                "bt_device_class": "0x002508",
                "max_connections": 1,
                "gyro_sensitivity": 1.0,
                "imu_poll_rate_hz": 100,
            }

    def _load(self) -> None:
        """Load config from disk, merging with defaults."""
        defaults = self._load_defaults()
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            user_config = {}

        with self._lock:
            self._data = {**defaults, **user_config}

    def save(self) -> None:
        """Persist current configuration to disk."""
        with self._lock:
            data_copy = dict(self._data)

        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(data_copy, f, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by key."""
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value and persist to disk."""
        with self._lock:
            self._data[key] = value
        self.save()

    def to_dict(self) -> dict[str, Any]:
        """Return a copy of the full configuration."""
        with self._lock:
            return dict(self._data)

    @property
    def controller_name(self) -> str:
        return self.get("controller_name", "Deck Controller")

    @controller_name.setter
    def controller_name(self, value: str) -> None:
        self.set("controller_name", value)

    @property
    def auto_connect(self) -> bool:
        return self.get("auto_connect", False)

    @auto_connect.setter
    def auto_connect(self, value: bool) -> None:
        self.set("auto_connect", value)

    @property
    def polling_rate_hz(self) -> int:
        return self.get("polling_rate_hz", 250)

    @polling_rate_hz.setter
    def polling_rate_hz(self, value: int) -> None:
        self.set("polling_rate_hz", value)

    @property
    def deadzone(self) -> float:
        return self.get("deadzone", 0.05)

    @deadzone.setter
    def deadzone(self, value: float) -> None:
        self.set("deadzone", value)

    @property
    def enable_gyro(self) -> bool:
        return self.get("enable_gyro", False)

    @enable_gyro.setter
    def enable_gyro(self, value: bool) -> None:
        self.set("enable_gyro", value)

    @property
    def enable_trackpads(self) -> bool:
        return self.get("enable_trackpads", False)

    @enable_trackpads.setter
    def enable_trackpads(self, value: bool) -> None:
        self.set("enable_trackpads", value)

    @property
    def bt_device_class(self) -> str:
        return self.get("bt_device_class", "0x002508")

    @bt_device_class.setter
    def bt_device_class(self, value: str) -> None:
        self.set("bt_device_class", value)

    @property
    def max_connections(self) -> int:
        return self.get("max_connections", 1)

    @max_connections.setter
    def max_connections(self, value: int) -> None:
        self.set("max_connections", value)
