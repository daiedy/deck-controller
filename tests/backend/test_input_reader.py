"""Tests for backend.input_reader — evdev input handling.

evdev is mocked via conftest.py's sys.modules setup.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.hid_descriptor import DPAD_NEUTRAL
from backend.input_reader import (
    DECK_CONTROLLER_NAMES,
    InputReader,
    InputState,
    _apply_deadzone,
    _BUTTON_MAP,
    _DPAD_MAP,
    STICK_MAX,
    TRIGGER_MAX,
)
import evdev
from evdev import ecodes


# ---- InputState ----


class TestInputState:
    def test_defaults(self):
        s = InputState()
        assert s.buttons == 0
        assert s.left_x == 0
        assert s.dpad == DPAD_NEUTRAL
        assert s.trackpad_right_touch is False

    def test_copy_is_independent(self):
        s = InputState(buttons=5, left_x=100)
        c = s.copy()
        c.buttons = 99
        assert s.buttons == 5

    def test_copy_preserves_values(self):
        s = InputState(left_x=10, right_y=20, dpad=3, trackpad_right_touch=True)
        c = s.copy()
        assert c.left_x == 10
        assert c.right_y == 20
        assert c.dpad == 3
        assert c.trackpad_right_touch is True


# ---- _apply_deadzone ----


class TestApplyDeadzone:
    def test_inside_deadzone_returns_zero(self):
        assert _apply_deadzone(100, 0.05, 32767) == 0

    def test_outside_deadzone_returns_value(self):
        assert _apply_deadzone(5000, 0.05, 32767) == 5000

    def test_negative_inside_deadzone(self):
        assert _apply_deadzone(-100, 0.05, 32767) == 0

    def test_negative_outside_deadzone(self):
        assert _apply_deadzone(-5000, 0.05, 32767) == -5000

    def test_zero_deadzone_passes_all(self):
        assert _apply_deadzone(1, 0.0, 32767) == 1

    def test_exact_threshold(self):
        threshold = int(32767 * 0.05)  # 1638
        assert _apply_deadzone(threshold - 1, 0.05, 32767) == 0
        # abs(threshold) is NOT < threshold, so it passes through
        assert _apply_deadzone(threshold, 0.05, 32767) == threshold
        assert _apply_deadzone(threshold + 1, 0.05, 32767) == threshold + 1


# ---- _BUTTON_MAP (populated because mock evdev is installed) ----


class TestButtonMap:
    def test_button_map_populated(self):
        assert len(_BUTTON_MAP) > 0

    def test_btn_a_mapping(self):
        assert _BUTTON_MAP[ecodes.BTN_A] == 0

    def test_btn_b_mapping(self):
        assert _BUTTON_MAP[ecodes.BTN_B] == 1

    def test_btn_start_mapping(self):
        assert _BUTTON_MAP[ecodes.BTN_START] == 9

    def test_paddle_buttons(self):
        assert _BUTTON_MAP[ecodes.BTN_TRIGGER_HAPPY1] == 13
        assert _BUTTON_MAP[ecodes.BTN_TRIGGER_HAPPY4] == 16


# ---- _DPAD_MAP ----


class TestDpadMap:
    def test_neutral(self):
        assert _DPAD_MAP[(0, 0)] == DPAD_NEUTRAL

    def test_up(self):
        assert _DPAD_MAP[(0, -1)] == 0

    def test_down_right(self):
        assert _DPAD_MAP[(1, 1)] == 3


# ---- InputReader.find_devices ----


class TestFindDevices:
    def test_no_devices(self):
        with patch.object(evdev, "list_devices", return_value=[]):
            devices = InputReader.find_devices()
            assert devices == []

    def test_finds_matching_device(self):
        mock_dev = MagicMock()
        mock_dev.name = "Steam Deck Controller"
        mock_dev.path = "/dev/input/event5"
        mock_dev.phys = "usb-0000:04:00.3"

        with patch.object(evdev, "list_devices", return_value=["/dev/input/event5"]), \
             patch("backend.input_reader.InputDevice", return_value=mock_dev):
            devices = InputReader.find_devices()
            assert len(devices) == 1
            assert devices[0]["name"] == "Steam Deck Controller"
            assert devices[0]["path"] == "/dev/input/event5"

    def test_skips_non_matching(self):
        mock_dev = MagicMock()
        mock_dev.name = "AT Keyboard"
        mock_dev.path = "/dev/input/event0"
        mock_dev.phys = ""

        with patch.object(evdev, "list_devices", return_value=["/dev/input/event0"]), \
             patch("backend.input_reader.InputDevice", return_value=mock_dev):
            devices = InputReader.find_devices()
            assert devices == []


# ---- InputReader lifecycle ----


class TestInputReaderLifecycle:
    def test_initial_state(self):
        reader = InputReader()
        assert reader.is_running is False

    async def test_start_no_device(self):
        reader = InputReader()
        with patch.object(evdev, "list_devices", return_value=[]):
            result = await reader.start(callback=lambda s: None)
            assert result is False
            assert reader.is_running is False

    def test_current_state_is_copy(self):
        reader = InputReader()
        s1 = reader.current_state
        s2 = reader.current_state
        s1.buttons = 999
        assert s2.buttons == 0


# ---- InputReader._process_event ----


class TestProcessEvent:
    def _make_reader(self) -> InputReader:
        reader = InputReader(deadzone=0.0)
        reader._callback = MagicMock()
        return reader

    def test_button_press(self, make_event):
        reader = self._make_reader()
        event = make_event(ecodes.EV_KEY, ecodes.BTN_A, 1)
        reader._process_event(event)
        assert reader._state.buttons & 1 == 1
        reader._callback.assert_called_once()

    def test_button_release(self, make_event):
        reader = self._make_reader()
        reader._state.buttons = 0x01  # A pressed
        event = make_event(ecodes.EV_KEY, ecodes.BTN_A, 0)
        reader._process_event(event)
        assert reader._state.buttons & 1 == 0

    def test_unknown_button_ignored(self, make_event):
        reader = self._make_reader()
        event = make_event(ecodes.EV_KEY, 9999, 1)
        reader._process_event(event)
        assert reader._state.buttons == 0
        reader._callback.assert_not_called()

    def test_left_stick_x(self, make_event):
        reader = self._make_reader()
        event = make_event(ecodes.EV_ABS, ecodes.ABS_X, 10000)
        reader._process_event(event)
        assert reader._state.left_x == 10000

    def test_right_stick_y(self, make_event):
        reader = self._make_reader()
        event = make_event(ecodes.EV_ABS, ecodes.ABS_RY, -5000)
        reader._process_event(event)
        assert reader._state.right_y == -5000

    def test_l2_trigger(self, make_event):
        reader = self._make_reader()
        event = make_event(ecodes.EV_ABS, ecodes.ABS_Z, 200)
        reader._process_event(event)
        assert reader._state.l2 == 200

    def test_r2_trigger(self, make_event):
        reader = self._make_reader()
        event = make_event(ecodes.EV_ABS, ecodes.ABS_RZ, 128)
        reader._process_event(event)
        assert reader._state.r2 == 128

    def test_trigger_clamped(self, make_event):
        reader = self._make_reader()
        event = make_event(ecodes.EV_ABS, ecodes.ABS_Z, 999)
        reader._process_event(event)
        assert reader._state.l2 == 255

    def test_dpad_up(self, make_event):
        reader = self._make_reader()
        # HAT0Y = -1 → up
        event = make_event(ecodes.EV_ABS, ecodes.ABS_HAT0Y, -1)
        reader._process_event(event)
        assert reader._state.dpad == 0  # up

    def test_dpad_right(self, make_event):
        reader = self._make_reader()
        event = make_event(ecodes.EV_ABS, ecodes.ABS_HAT0X, 1)
        reader._process_event(event)
        assert reader._state.dpad == 2  # right

    def test_dpad_neutral(self, make_event):
        reader = self._make_reader()
        reader._hat_x = 1
        event = make_event(ecodes.EV_ABS, ecodes.ABS_HAT0X, 0)
        reader._process_event(event)
        assert reader._state.dpad == DPAD_NEUTRAL

    def test_trackpad_right(self, make_event):
        reader = self._make_reader()
        event = make_event(ecodes.EV_ABS, ecodes.ABS_HAT3X, 16000)
        reader._process_event(event)
        assert reader._state.trackpad_right_x == 16000
        assert reader._state.trackpad_right_touch is True

    def test_trackpad_left(self, make_event):
        reader = self._make_reader()
        event = make_event(ecodes.EV_ABS, ecodes.ABS_HAT2Y, 8000)
        reader._process_event(event)
        assert reader._state.trackpad_left_y == 8000
        assert reader._state.trackpad_left_touch is True

    def test_trackpad_touch_zero_means_not_touching(self, make_event):
        reader = self._make_reader()
        event = make_event(ecodes.EV_ABS, ecodes.ABS_HAT3X, 0)
        reader._process_event(event)
        assert reader._state.trackpad_right_touch is False

    def test_deadzone_applied(self, make_event):
        reader = InputReader(deadzone=0.1)
        reader._callback = MagicMock()
        # 32767 * 0.1 = 3276 → value 1000 < threshold → zeroed
        event = make_event(ecodes.EV_ABS, ecodes.ABS_X, 1000)
        reader._process_event(event)
        assert reader._state.left_x == 0

    def test_callback_receives_state_copy(self, make_event):
        reader = self._make_reader()
        received = []
        reader._callback = lambda s: received.append(s)
        event = make_event(ecodes.EV_KEY, ecodes.BTN_A, 1)
        reader._process_event(event)
        assert len(received) == 1
        # Mutating returned state shouldn't affect internal state
        received[0].buttons = 9999
        assert reader._state.buttons != 9999


# ---- InputReader async lifecycle ----


class TestInputReaderAsyncLifecycle:
    async def test_start_already_running(self):
        reader = InputReader()
        reader._running = True
        result = await reader.start(callback=lambda s: None)
        assert result is False

    async def test_start_success_and_stop(self):
        reader = InputReader()
        mock_dev = MagicMock()
        mock_dev.name = "Microsoft X-Box 360 pad"
        mock_dev.path = "/dev/input/event5"
        mock_dev.grab = MagicMock()
        mock_dev.ungrab = MagicMock()
        mock_dev.close = MagicMock()

        # Make async_read_loop a finite async generator
        async def _fake_read():
            return
            yield  # makes it an async generator

        mock_dev.async_read_loop = _fake_read

        with patch.object(reader, "_find_device", return_value=mock_dev):
            result = await reader.start(callback=MagicMock())
            assert result is True
            assert reader.is_running is True
            assert reader._grabbed is True
            mock_dev.grab.assert_called_once()

            await reader.stop()
            assert reader.is_running is False
            mock_dev.ungrab.assert_called_once()
            mock_dev.close.assert_called_once()

    async def test_start_grab_failure(self):
        reader = InputReader()
        mock_dev = MagicMock()
        mock_dev.name = "Steam Deck"
        mock_dev.path = "/dev/input/event3"
        mock_dev.grab = MagicMock(side_effect=OSError("grab failed"))
        mock_dev.close = MagicMock()

        async def _fake_read():
            return
            yield

        mock_dev.async_read_loop = _fake_read

        with patch.object(reader, "_find_device", return_value=mock_dev):
            result = await reader.start(callback=MagicMock())
            assert result is True
            assert reader._grabbed is False
            await reader.stop()

    async def test_start_no_grab(self):
        reader = InputReader()
        mock_dev = MagicMock()
        mock_dev.name = "Steam Deck"
        mock_dev.path = "/dev/input/event3"
        mock_dev.close = MagicMock()

        async def _fake_read():
            return
            yield

        mock_dev.async_read_loop = _fake_read

        with patch.object(reader, "_find_device", return_value=mock_dev):
            result = await reader.start(callback=MagicMock(), grab=False)
            assert result is True
            assert reader._grabbed is False
            mock_dev.grab.assert_not_called()
            await reader.stop()

    async def test_read_loop_oserror_stops(self):
        reader = InputReader()
        mock_dev = MagicMock()
        mock_dev.name = "Steam Deck"
        mock_dev.path = "/dev/input/event3"
        mock_dev.grab = MagicMock()
        mock_dev.ungrab = MagicMock()
        mock_dev.close = MagicMock()

        async def _error_read():
            raise OSError("device gone")
            yield

        mock_dev.async_read_loop = _error_read

        with patch.object(reader, "_find_device", return_value=mock_dev):
            await reader.start(callback=MagicMock())
            # Wait for task to finish
            await asyncio.sleep(0.05)
            assert reader._running is False
            await reader.stop()

    async def test_stop_when_not_started(self):
        reader = InputReader()
        await reader.stop()  # should not raise

    def test_find_device_returns_matching(self):
        reader = InputReader()
        mock_dev = MagicMock()
        mock_dev.name = "Microsoft X-Box 360 pad"
        mock_dev.path = "/dev/input/event1"
        mock_dev.close = MagicMock()

        with patch.object(evdev, "list_devices", return_value=["/dev/input/event1"]), \
             patch("backend.input_reader.InputDevice", return_value=mock_dev):
            result = reader._find_device()
            assert result is not None
            assert result.path == "/dev/input/event1"

    def test_find_device_no_match(self):
        reader = InputReader()
        mock_dev = MagicMock()
        mock_dev.name = "AT Keyboard"
        mock_dev.path = "/dev/input/event0"
        mock_dev.close = MagicMock()

        with patch.object(evdev, "list_devices", return_value=["/dev/input/event0"]), \
             patch("backend.input_reader.InputDevice", return_value=mock_dev):
            result = reader._find_device()
            assert result is None

    def test_find_device_oserror(self):
        reader = InputReader()
        with patch.object(evdev, "list_devices", return_value=["/dev/input/event0"]), \
             patch("backend.input_reader.InputDevice", side_effect=OSError("nope")):
            result = reader._find_device()
            assert result is None
