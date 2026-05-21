"""Deck Controller — DeckyLoader Plugin Entry Point.

Turns the Steam Deck into a Bluetooth HID gamepad controller.
"""

from __future__ import annotations

# Add plugin directory to sys.path so subpackage imports work in DeckyLoader sandbox
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import asyncio  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from typing import Any  # noqa: E402

# DeckyLoader provides this module at runtime
try:
    import decky  # type: ignore[import-untyped]
except ImportError:
    # Stub for development/type checking outside DeckyLoader
    class _DeckyStub:  # type: ignore[no-redef]
        DECKY_PLUGIN_SETTINGS_DIR = ""
        logger = logging.getLogger("decky")

        @staticmethod
        def emit(event: str, *args: Any) -> None:
            pass

    decky = _DeckyStub()  # type: ignore[assignment]

from backend.bt_hid_service import BTHIDService  # noqa: E402
from backend.config import Config  # noqa: E402
from backend.hid_descriptor import DPAD_NEUTRAL, pack_motion_report, pack_report  # noqa: E402
from backend.imu_reader import IMUReader, MotionState  # noqa: E402
from backend.input_reader import InputReader, InputState  # noqa: E402
from backend.profile_manager import Profile, ProfileManager  # noqa: E402
from backend.trackpad_mouse import TrackpadMouse  # noqa: E402

logger = decky.logger if hasattr(decky, "logger") else logging.getLogger("deck-controller")


class Plugin:
    """DeckyLoader plugin that emulates a Bluetooth HID gamepad."""

    bt_service: BTHIDService
    input_reader: InputReader
    config: Config
    trackpad_mouse: TrackpadMouse
    imu_reader: IMUReader
    profile_manager: ProfileManager
    _report_task: asyncio.Task[None] | None = None

    async def _main(self) -> None:
        """Plugin initialization — called by DeckyLoader on load."""
        logger.info("Deck Controller plugin loading...")

        self.config = Config()
        self.bt_service = BTHIDService()
        self.input_reader = InputReader(deadzone=self.config.deadzone)
        self.trackpad_mouse = TrackpadMouse(
            sensitivity=self.config.get("mouse_sensitivity", 1.0),
            scroll_sensitivity=self.config.get("scroll_sensitivity", 1.0),
        )
        self.imu_reader = IMUReader()
        self.profile_manager = ProfileManager(
            settings_dir=os.environ.get(
                "DECKY_PLUGIN_SETTINGS_DIR",
                os.path.expanduser("~/homebrew/settings/deck-controller"),
            )
        )

        logger.info("Deck Controller plugin loaded")

    async def _unload(self) -> None:
        """Plugin shutdown — called by DeckyLoader on unload.

        Must clean up everything: stop input reading, close BT sockets,
        restore bluetoothd to its original state.
        """
        logger.info("Deck Controller plugin unloading...")

        if self._report_task is not None:
            self._report_task.cancel()
            try:
                await self._report_task
            except asyncio.CancelledError:
                pass
            self._report_task = None

        await self.input_reader.stop()
        await self.imu_reader.stop()
        await self.bt_service.stop()

        logger.info("Deck Controller plugin unloaded")

    async def _uninstall(self) -> None:
        """Called when the plugin is uninstalled."""
        logger.info("Deck Controller plugin uninstalling")
        await self._unload()

    def _toggle_gamepad_mode(self) -> None:
        """Toggle between gamepad mode (input to BT host) and local mode.

        Called by InputReader when L4+R4 combo is pressed.
        """
        new_state = self.input_reader.toggle_grab()
        if new_state:
            logger.info("Gamepad mode ENABLED — input forwarded to BT host")
        else:
            logger.info("Gamepad mode DISABLED — Steam Deck controls restored")
            # Send neutral report to release all buttons/axes on host
            neutral = pack_report(0, 0, 0, 0, 0, 0, 0, DPAD_NEUTRAL)
            self.bt_service.send_report(neutral)

    def _on_input_state_change(self, state: InputState) -> None:
        """Callback for input state changes — sends HID reports based on active profile."""
        if not hasattr(self, "_input_cb_count"):
            self._input_cb_count = 0
        self._input_cb_count += 1
        if self._input_cb_count <= 5 or self._input_cb_count % 500 == 0:
            logger.info(
                "Input callback #%d: buttons=0x%04x lx=%d ly=%d",
                self._input_cb_count,
                state.buttons,
                state.left_x,
                state.left_y,
            )
        profile = self.profile_manager.active_profile

        # Gamepad report
        if profile.sends_gamepad():
            report = pack_report(
                buttons=state.buttons,
                left_x=state.left_x,
                left_y=state.left_y,
                right_x=state.right_x,
                right_y=state.right_y,
                l2=state.l2,
                r2=state.r2,
                dpad=state.dpad,
            )
            self.bt_service.send_report(report)

        # Mouse report
        if profile.sends_mouse() and profile.trackpad_mode == "mouse":
            dx, dy = self.trackpad_mouse.update_right(
                state.trackpad_right_x,
                state.trackpad_right_y,
                state.trackpad_right_touch,
            )
            wheel = self.trackpad_mouse.update_left(
                state.trackpad_left_y,
                state.trackpad_left_touch,
            )
            mouse_buttons = 0
            if state.trackpad_right_click:
                mouse_buttons |= 0x01  # Left click
            if state.trackpad_left_click:
                mouse_buttons |= 0x04  # Middle click

            if dx or dy or wheel or mouse_buttons:
                self.bt_service.send_mouse_report(mouse_buttons, dx, dy, wheel)

    def _on_motion_state_change(self, state: MotionState) -> None:
        """Callback for IMU state changes — sends motion HID report."""
        report = pack_motion_report(
            gyro_x=state.gyro_x,
            gyro_y=state.gyro_y,
            gyro_z=state.gyro_z,
            accel_x=state.accel_x,
            accel_y=state.accel_y,
            accel_z=state.accel_z,
        )
        self.bt_service.send_report(report)

    # --- Exposed RPC Methods ---

    async def start_broadcasting(self) -> dict[str, Any]:
        """Start Bluetooth discoverable mode and input reading.

        Returns:
            Dict with 'success' boolean and status info.
        """
        try:
            bt_started = await self.bt_service.start(
                controller_name=self.config.controller_name,
                device_class=self.config.bt_device_class,
            )
            if not bt_started:
                return {"success": False, "error": "Failed to start Bluetooth service"}

            input_started = await self.input_reader.start(
                callback=self._on_input_state_change,
                grab=True,
                toggle_callback=self._toggle_gamepad_mode,
            )
            if not input_started:
                await self.bt_service.stop()
                return {"success": False, "error": "Failed to start input reader"}

            # Start IMU if active profile uses motion
            if self.profile_manager.active_profile.sends_motion():
                imu_started = await self.imu_reader.start(callback=self._on_motion_state_change)
                if not imu_started:
                    logger.warning("IMU not available — motion disabled")

            status = self.bt_service.get_status()
            decky.emit("status_changed", status)
            return {"success": True, **status}

        except Exception as e:
            logger.error("Error starting broadcasting: %s", e)
            return {"success": False, "error": str(e)}

    async def stop_broadcasting(self) -> dict[str, Any]:
        """Stop broadcasting and input reading.

        Returns:
            Dict with 'success' boolean.
        """
        try:
            await self.input_reader.stop()
            await self.imu_reader.stop()
            await self.bt_service.stop()

            status = self.bt_service.get_status()
            decky.emit("status_changed", status)
            return {"success": True, **status}

        except Exception as e:
            logger.error("Error stopping broadcasting: %s", e)
            return {"success": False, "error": str(e)}

    async def get_status(self) -> dict[str, Any]:
        """Get current plugin status.

        Returns:
            Dict with state, connected device info, and running flags.
        """
        bt_status = self.bt_service.get_status()
        return {
            "success": True,
            **bt_status,
            "input_active": self.input_reader.is_running,
        }

    async def get_devices(self) -> list[dict[str, str]]:
        """Get list of paired Bluetooth devices.

        Returns:
            List of device dicts with 'address' and 'name'.
        """
        return self.bt_service.get_paired_devices()

    async def set_config(self, key: str, value: Any) -> dict[str, Any]:
        """Update a configuration value.

        Args:
            key: Configuration key name.
            value: New value.

        Returns:
            Dict with 'success' and the updated config.
        """
        ALLOWED_KEYS = {
            "controller_name",
            "auto_connect",
            "polling_rate_hz",
            "deadzone",
            "enable_gyro",
            "enable_trackpads",
            "bt_device_class",
            "max_connections",
            "mouse_sensitivity",
            "scroll_sensitivity",
            "gyro_sensitivity",
            "imu_poll_rate_hz",
        }
        VALID_POLLING_RATES = {125, 250, 500}

        if key not in ALLOWED_KEYS:
            return {"success": False, "error": f"Unknown config key: {key}"}

        try:
            if key == "deadzone":
                val = float(value)
                if not (0.0 <= val <= 0.5):
                    return {"success": False, "error": "deadzone must be between 0.0 and 0.5"}
                value = val
            elif key == "polling_rate_hz":
                val = int(value)
                if val not in VALID_POLLING_RATES:
                    return {
                        "success": False,
                        "error": f"polling_rate_hz must be one of {VALID_POLLING_RATES}",
                    }
                value = val

            self.config.set(key, value)

            # Apply runtime changes
            if key == "deadzone":
                self.input_reader._deadzone = float(value)

            return {"success": True, "config": self.config.to_dict()}
        except Exception as e:
            logger.error("Error setting config %s=%s: %s", key, value, e)
            return {"success": False, "error": str(e)}

    async def get_config(self) -> dict[str, Any]:
        """Get the full plugin configuration.

        Returns:
            Dict with 'success' and the full config.
        """
        return {"success": True, "config": self.config.to_dict()}

    async def enable_gyro(self) -> dict[str, Any]:
        """Enable gyroscope/motion sensor."""
        if self.imu_reader.is_running:
            return {"success": True, "message": "Already running"}
        started = await self.imu_reader.start(callback=self._on_motion_state_change)
        if started:
            self.config.set("enable_gyro", True)
            return {"success": True}
        return {"success": False, "error": "IMU device not found"}

    async def disable_gyro(self) -> dict[str, Any]:
        """Disable gyroscope/motion sensor."""
        await self.imu_reader.stop()
        self.config.set("enable_gyro", False)
        return {"success": True}

    async def remove_device(self, address: str) -> dict[str, Any]:
        """Remove a paired BT device.

        Args:
            address: Bluetooth MAC address of the device.

        Returns:
            Dict with 'success' boolean.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "bluetoothctl",
                "remove",
                address,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
            return {"success": proc.returncode == 0}
        except Exception as e:
            logger.error("Error removing device %s: %s", address, e)
            return {"success": False, "error": str(e)}

    async def log_frontend_error(
        self, error: str, stack: str = "", component: str = "", url: str = ""
    ) -> dict[str, Any]:
        """Log a frontend error to file and decky logger."""
        settings_dir = os.environ.get(
            "DECKY_PLUGIN_SETTINGS_DIR",
            os.path.expanduser("~/homebrew/settings/deck-controller"),
        )
        log_path = os.path.join(settings_dir, "frontend-errors.log")
        os.makedirs(settings_dir, exist_ok=True)

        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{ts}] error={error}"
        if component:
            entry += f" component={component}"
        if url:
            entry += f" url={url}"
        if stack:
            entry += f"\n  stack: {stack}"
        entry += "\n"

        logger.error("Frontend error: %s (component=%s)", error, component)

        try:
            with open(log_path, "a") as f:
                f.write(entry)

            # Truncate if > 100KB: keep last half of lines
            if os.path.getsize(log_path) > 100 * 1024:
                with open(log_path, "r") as f:
                    lines = f.readlines()
                with open(log_path, "w") as f:
                    f.writelines(lines[len(lines) // 2 :])
        except Exception as e:
            logger.error("Failed to write frontend error log: %s", e)

        return {"success": True}

    # --- Profile RPC Methods ---

    async def get_profiles(self) -> dict[str, Any]:
        """Get all profiles and active profile info."""
        return {"success": True, **self.profile_manager.to_dict()}

    async def switch_profile(self, index: int) -> dict[str, Any]:
        """Switch active profile by index."""
        try:
            profile = self.profile_manager.switch_profile(index)
            # Apply profile settings
            self.trackpad_mouse.sensitivity = profile.mouse_sensitivity
            self.trackpad_mouse.scroll_sensitivity = profile.scroll_sensitivity
            # Start/stop IMU based on new profile
            if profile.sends_motion() and not self.imu_reader.is_running:
                await self.imu_reader.start(callback=self._on_motion_state_change)
            elif not profile.sends_motion() and self.imu_reader.is_running:
                await self.imu_reader.stop()
            # Reset trackpad state on profile switch
            self.trackpad_mouse.reset()
            decky.emit("profile_changed", profile.to_dict())
            return {"success": True, "profile": profile.to_dict()}
        except IndexError as e:
            return {"success": False, "error": str(e)}

    async def add_profile(self, profile_data: dict[str, Any]) -> dict[str, Any]:
        """Add a new custom profile."""
        try:
            profile = Profile.from_dict(profile_data)
            index = self.profile_manager.add_profile(profile)
            return {"success": True, "index": index, "profile": profile.to_dict()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def remove_profile(self, index: int) -> dict[str, Any]:
        """Remove a profile by index."""
        if self.profile_manager.remove_profile(index):
            return {"success": True, **self.profile_manager.to_dict()}
        return {
            "success": False,
            "error": "Cannot remove (minimum 1 profile required or invalid index)",
        }
