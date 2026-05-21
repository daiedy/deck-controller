"""Tests for main.py — Plugin class RPC methods.

All backend dependencies are mocked.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from main import Plugin
from backend.input_reader import InputState
from backend.imu_reader import MotionState
from backend.profile_manager import Profile


# ---- Helpers ----


def _make_plugin() -> Plugin:
    """Create a Plugin with all backend deps mocked."""
    p = Plugin()
    p.config = MagicMock()
    p.config.controller_name = "TestDeck"
    p.config.bt_device_class = "0x002508"
    p.config.deadzone = 0.05
    p.config.to_dict.return_value = {"controller_name": "TestDeck"}
    p.config.get.return_value = 1.0

    p.bt_service = MagicMock()
    p.bt_service.start = AsyncMock(return_value=True)
    p.bt_service.stop = AsyncMock()
    p.bt_service.get_status.return_value = {
        "state": "idle",
        "running": False,
        "connected_device": None,
    }
    p.bt_service.get_paired_devices.return_value = []
    p.bt_service.send_report = MagicMock(return_value=True)

    p.input_reader = MagicMock()
    p.input_reader.start = AsyncMock(return_value=True)
    p.input_reader.stop = AsyncMock()
    p.input_reader.is_running = False

    p.imu_reader = MagicMock()
    p.imu_reader.start = AsyncMock(return_value=True)
    p.imu_reader.stop = AsyncMock()
    p.imu_reader.is_running = False

    p.trackpad_mouse = MagicMock()
    p.trackpad_mouse.sensitivity = 1.0
    p.trackpad_mouse.scroll_sensitivity = 1.0
    p.trackpad_mouse.update_right.return_value = (0, 0)
    p.trackpad_mouse.update_left.return_value = 0

    p.profile_manager = MagicMock()
    active = Profile(name="Default", active_reports=["gamepad"])
    p.profile_manager.active_profile = active
    p.profile_manager.to_dict.return_value = {
        "profiles": [active.to_dict()],
        "active_index": 0,
        "active_profile": active.to_dict(),
    }

    p._report_task = None
    return p


# ---- _main ----


class TestPluginMain:
    async def test_main_initializes_components(self):
        with patch("main.Config") as MockConfig, \
             patch("main.BTHIDService") as MockBT, \
             patch("main.InputReader") as MockInput, \
             patch("main.IMUReader") as MockIMU, \
             patch("main.ProfileManager") as MockPM, \
             patch("main.TrackpadMouse") as MockTM:

            MockConfig.return_value.deadzone = 0.05
            MockConfig.return_value.get.return_value = 1.0

            plugin = Plugin()
            await plugin._main()

            MockConfig.assert_called_once()
            MockBT.assert_called_once()
            MockInput.assert_called_once_with(deadzone=0.05)
            MockIMU.assert_called_once()
            MockPM.assert_called_once()
            MockTM.assert_called_once()


# ---- _unload ----


class TestPluginUnload:
    async def test_unload_stops_everything(self):
        p = _make_plugin()
        await p._unload()

        p.input_reader.stop.assert_awaited_once()
        p.imu_reader.stop.assert_awaited_once()
        p.bt_service.stop.assert_awaited_once()

    async def test_unload_cancels_report_task(self):
        p = _make_plugin()

        async def _never_finish():
            await asyncio.sleep(999)

        p._report_task = asyncio.create_task(_never_finish())
        await p._unload()
        assert p._report_task is None


# ---- start_broadcasting ----


class TestStartBroadcasting:
    async def test_success(self):
        p = _make_plugin()
        p.bt_service.get_status.return_value = {
            "state": "broadcasting",
            "running": True,
            "connected_device": None,
        }

        result = await p.start_broadcasting()
        assert result["success"] is True
        p.bt_service.start.assert_awaited_once()
        p.input_reader.start.assert_awaited_once()

    async def test_bt_failure(self):
        p = _make_plugin()
        p.bt_service.start = AsyncMock(return_value=False)

        result = await p.start_broadcasting()
        assert result["success"] is False
        assert "error" in result

    async def test_input_failure_stops_bt(self):
        p = _make_plugin()
        p.input_reader.start = AsyncMock(return_value=False)

        result = await p.start_broadcasting()
        assert result["success"] is False
        p.bt_service.stop.assert_awaited_once()

    async def test_starts_imu_for_motion_profile(self):
        p = _make_plugin()
        p.profile_manager.active_profile = Profile(
            name="Motion", active_reports=["gamepad", "motion"]
        )
        p.bt_service.get_status.return_value = {
            "state": "broadcasting", "running": True, "connected_device": None,
        }

        await p.start_broadcasting()
        p.imu_reader.start.assert_awaited_once()


# ---- stop_broadcasting ----


class TestStopBroadcasting:
    async def test_success(self):
        p = _make_plugin()
        result = await p.stop_broadcasting()
        assert result["success"] is True
        p.input_reader.stop.assert_awaited_once()
        p.imu_reader.stop.assert_awaited_once()
        p.bt_service.stop.assert_awaited_once()


# ---- get_status ----


class TestGetStatus:
    async def test_returns_status(self):
        p = _make_plugin()
        result = await p.get_status()
        assert result["success"] is True
        assert result["state"] == "idle"
        assert result["input_active"] is False


# ---- get_devices ----


class TestGetDevices:
    async def test_returns_paired_devices(self):
        p = _make_plugin()
        p.bt_service.get_paired_devices.return_value = [
            {"address": "AA:BB:CC:DD:EE:FF", "name": "Phone"}
        ]
        result = await p.get_devices()
        assert len(result) == 1
        assert result[0]["name"] == "Phone"


# ---- set_config ----


class TestSetConfig:
    async def test_valid_key(self):
        p = _make_plugin()
        result = await p.set_config("controller_name", "NewName")
        assert result["success"] is True
        p.config.set.assert_called_with("controller_name", "NewName")

    async def test_unknown_key(self):
        p = _make_plugin()
        result = await p.set_config("nonexistent_key", "value")
        assert result["success"] is False

    async def test_deadzone_validation(self):
        p = _make_plugin()
        result = await p.set_config("deadzone", 0.6)
        assert result["success"] is False

    async def test_deadzone_valid(self):
        p = _make_plugin()
        result = await p.set_config("deadzone", 0.1)
        assert result["success"] is True

    async def test_polling_rate_validation(self):
        p = _make_plugin()
        result = await p.set_config("polling_rate_hz", 999)
        assert result["success"] is False

    async def test_polling_rate_valid(self):
        p = _make_plugin()
        result = await p.set_config("polling_rate_hz", 250)
        assert result["success"] is True

    async def test_deadzone_updates_reader(self):
        p = _make_plugin()
        await p.set_config("deadzone", 0.15)
        assert p.input_reader._deadzone == 0.15


# ---- get_config ----


class TestGetConfig:
    async def test_returns_config(self):
        p = _make_plugin()
        result = await p.get_config()
        assert result["success"] is True
        assert "config" in result


# ---- enable_gyro / disable_gyro ----


class TestGyroToggle:
    async def test_enable_gyro(self):
        p = _make_plugin()
        result = await p.enable_gyro()
        assert result["success"] is True
        p.imu_reader.start.assert_awaited_once()

    async def test_enable_gyro_already_running(self):
        p = _make_plugin()
        p.imu_reader.is_running = True
        result = await p.enable_gyro()
        assert result["success"] is True
        assert "Already running" in result.get("message", "")

    async def test_enable_gyro_failure(self):
        p = _make_plugin()
        p.imu_reader.start = AsyncMock(return_value=False)
        result = await p.enable_gyro()
        assert result["success"] is False

    async def test_disable_gyro(self):
        p = _make_plugin()
        result = await p.disable_gyro()
        assert result["success"] is True
        p.imu_reader.stop.assert_awaited_once()


# ---- remove_device ----


class TestRemoveDevice:
    async def test_success(self):
        p = _make_plugin()
        with patch("main.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_exec.return_value = mock_proc

            result = await p.remove_device("AA:BB:CC:DD:EE:FF")
            assert result["success"] is True


# ---- get_profiles ----


class TestGetProfiles:
    async def test_returns_profiles(self):
        p = _make_plugin()
        result = await p.get_profiles()
        assert result["success"] is True
        assert "profiles" in result


# ---- switch_profile ----


class TestSwitchProfile:
    async def test_switch_success(self):
        p = _make_plugin()
        target = Profile(name="FPS", active_reports=["gamepad"], mouse_sensitivity=0.5)
        p.profile_manager.switch_profile.return_value = target

        result = await p.switch_profile(1)
        assert result["success"] is True
        assert result["profile"]["name"] == "FPS"
        assert p.trackpad_mouse.sensitivity == 0.5

    async def test_switch_resets_trackpad(self):
        p = _make_plugin()
        target = Profile(name="FPS")
        p.profile_manager.switch_profile.return_value = target

        await p.switch_profile(1)
        p.trackpad_mouse.reset.assert_called_once()

    async def test_switch_invalid_index(self):
        p = _make_plugin()
        p.profile_manager.switch_profile.side_effect = IndexError("out of range")

        result = await p.switch_profile(99)
        assert result["success"] is False

    async def test_switch_starts_imu_for_motion(self):
        p = _make_plugin()
        target = Profile(name="Motion", active_reports=["gamepad", "motion"])
        p.profile_manager.switch_profile.return_value = target

        await p.switch_profile(1)
        p.imu_reader.start.assert_awaited_once()

    async def test_switch_stops_imu_when_not_needed(self):
        p = _make_plugin()
        p.imu_reader.is_running = True
        target = Profile(name="NoMotion", active_reports=["gamepad"])
        p.profile_manager.switch_profile.return_value = target

        await p.switch_profile(0)
        p.imu_reader.stop.assert_awaited_once()


# ---- add_profile ----


class TestAddProfile:
    async def test_add_success(self):
        p = _make_plugin()
        p.profile_manager.add_profile.return_value = 4

        result = await p.add_profile({"name": "Custom"})
        assert result["success"] is True
        assert result["index"] == 4


# ---- remove_profile ----


class TestRemoveProfile:
    async def test_remove_success(self):
        p = _make_plugin()
        p.profile_manager.remove_profile.return_value = True

        result = await p.remove_profile(1)
        assert result["success"] is True

    async def test_remove_failure(self):
        p = _make_plugin()
        p.profile_manager.remove_profile.return_value = False

        result = await p.remove_profile(0)
        assert result["success"] is False


# ---- _on_input_state_change ----


class TestOnInputStateChange:
    def test_sends_gamepad_report(self):
        p = _make_plugin()
        p.profile_manager.active_profile = Profile(
            name="GP", active_reports=["gamepad"]
        )

        state = InputState(buttons=1, left_x=100)
        p._on_input_state_change(state)
        p.bt_service.send_report.assert_called_once()

    def test_sends_mouse_report(self):
        p = _make_plugin()
        p.profile_manager.active_profile = Profile(
            name="Mouse",
            active_reports=["mouse"],
            trackpad_mode="mouse",
        )
        p.trackpad_mouse.update_right.return_value = (5, 3)
        p.trackpad_mouse.update_left.return_value = 0

        state = InputState(trackpad_right_touch=True, trackpad_right_x=100)
        p._on_input_state_change(state)
        p.bt_service.send_mouse_report.assert_called_once_with(0, 5, 3, 0)

    def test_mouse_report_skipped_when_no_movement(self):
        p = _make_plugin()
        p.profile_manager.active_profile = Profile(
            name="Mouse",
            active_reports=["mouse"],
            trackpad_mode="mouse",
        )
        p.trackpad_mouse.update_right.return_value = (0, 0)
        p.trackpad_mouse.update_left.return_value = 0

        state = InputState()
        p._on_input_state_change(state)
        p.bt_service.send_mouse_report.assert_not_called()

    def test_right_click_sets_left_button(self):
        p = _make_plugin()
        p.profile_manager.active_profile = Profile(
            name="Mouse",
            active_reports=["mouse"],
            trackpad_mode="mouse",
        )
        p.trackpad_mouse.update_right.return_value = (0, 0)
        p.trackpad_mouse.update_left.return_value = 0

        state = InputState(trackpad_right_click=True)
        p._on_input_state_change(state)
        # mouse_buttons=0x01 triggers a report
        p.bt_service.send_mouse_report.assert_called_once()


# ---- _on_motion_state_change ----


class TestOnMotionStateChange:
    def test_sends_motion_report(self):
        p = _make_plugin()
        state = MotionState(gyro_x=10, accel_z=16000)
        p._on_motion_state_change(state)
        p.bt_service.send_report.assert_called_once()
