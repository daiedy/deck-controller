"""Shared test fixtures and mock setup for deck-controller tests.

IMPORTANT: The mock evdev module is installed into sys.modules at import time
(before any backend modules are loaded) so that backend code sees evdev as
available and initializes module-level structures like _BUTTON_MAP.
"""

from __future__ import annotations

import json
import sys
from types import ModuleType
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Mock evdev — MUST happen before any backend imports
# ---------------------------------------------------------------------------

_mock_evdev = ModuleType("evdev")
_mock_evdev.__package__ = "evdev"


class _Ecodes:
    """Mock evdev.ecodes with real Linux input-event constant values."""

    # Event types
    EV_SYN = 0x00
    EV_KEY = 0x01
    EV_ABS = 0x03

    # Button codes
    BTN_A = 0x130       # 304
    BTN_B = 0x131       # 305
    BTN_X = 0x133       # 307
    BTN_Y = 0x134       # 308
    BTN_TL = 0x136      # 310
    BTN_TR = 0x137      # 311
    BTN_TL2 = 0x138     # 312
    BTN_TR2 = 0x139     # 313
    BTN_SELECT = 0x13A  # 314
    BTN_START = 0x13B   # 315
    BTN_MODE = 0x13C    # 316
    BTN_THUMBL = 0x13D  # 317
    BTN_THUMBR = 0x13E  # 318
    BTN_TRIGGER_HAPPY1 = 0x2C0  # 704
    BTN_TRIGGER_HAPPY2 = 0x2C1  # 705
    BTN_TRIGGER_HAPPY3 = 0x2C2  # 706
    BTN_TRIGGER_HAPPY4 = 0x2C3  # 707

    # Absolute axes
    ABS_X = 0x00
    ABS_Y = 0x01
    ABS_Z = 0x02
    ABS_RX = 0x03
    ABS_RY = 0x04
    ABS_RZ = 0x05
    ABS_HAT0X = 0x10  # 16
    ABS_HAT0Y = 0x11  # 17
    ABS_HAT2X = 0x14  # 20
    ABS_HAT2Y = 0x15  # 21
    ABS_HAT3X = 0x16  # 22
    ABS_HAT3Y = 0x17  # 23


_ecodes = _Ecodes()
_mock_evdev.ecodes = _ecodes
_mock_evdev.InputDevice = MagicMock()
_mock_evdev.categorize = MagicMock()
_mock_evdev.list_devices = MagicMock(return_value=[])

# Install into sys.modules and force-reimport any cached backend modules
sys.modules["evdev"] = _mock_evdev
for _mod in [k for k in sys.modules if k.startswith("backend.")]:
    del sys.modules[_mod]

# ---------------------------------------------------------------------------
# Now it is safe to import from backend
# ---------------------------------------------------------------------------

import pytest  # noqa: E402


class _EvdevEvent:
    """Lightweight stand-in for an evdev InputEvent."""

    __slots__ = ("type", "code", "value")

    def __init__(self, etype: int, code: int, value: int) -> None:
        self.type = etype
        self.code = code
        self.value = value


@pytest.fixture()
def make_event():
    """Factory fixture that creates mock evdev events."""
    return _EvdevEvent


@pytest.fixture()
def defaults_json(tmp_path):
    """Write a defaults.json file and return its path."""
    data = {
        "controller_name": "Deck Controller",
        "auto_connect": False,
        "polling_rate_hz": 250,
        "deadzone": 0.05,
        "enable_gyro": False,
        "enable_trackpads": False,
        "bt_device_class": "0x002508",
        "max_connections": 1,
    }
    p = tmp_path / "defaults.json"
    p.write_text(json.dumps(data))
    return str(p)
