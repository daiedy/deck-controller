"""Deck Controller — DeckyLoader Plugin Entry Point.

Turns the Steam Deck into a Bluetooth HID gamepad controller.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

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

from backend.bt_hid_service import BTHIDService
from backend.config import Config
from backend.hid_descriptor import pack_report
from backend.input_reader import InputReader, InputState

logger = decky.logger if hasattr(decky, "logger") else logging.getLogger("deck-controller")


class Plugin:
    """DeckyLoader plugin that emulates a Bluetooth HID gamepad."""

    bt_service: BTHIDService
    input_reader: InputReader
    config: Config
    _report_task: asyncio.Task[None] | None = None

    async def _main(self) -> None:
        """Plugin initialization — called by DeckyLoader on load."""
        logger.info("Deck Controller plugin loading...")

        self.config = Config()
        self.bt_service = BTHIDService()
        self.input_reader = InputReader(deadzone=self.config.deadzone)

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
        await self.bt_service.stop()

        logger.info("Deck Controller plugin unloaded")

    async def _uninstall(self) -> None:
        """Called when the plugin is uninstalled."""
        logger.info("Deck Controller plugin uninstalling")
        await self._unload()

    def _on_input_state_change(self, state: InputState) -> None:
        """Callback for input state changes — sends HID report to connected device."""
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
            )
            if not input_started:
                await self.bt_service.stop()
                return {"success": False, "error": "Failed to start input reader"}

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
            "controller_name", "auto_connect", "polling_rate_hz",
            "deadzone", "enable_gyro", "enable_trackpads",
            "bt_device_class", "max_connections",
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
                    return {"success": False, "error": f"polling_rate_hz must be one of {VALID_POLLING_RATES}"}
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

    async def remove_device(self, address: str) -> dict[str, Any]:
        """Remove a paired BT device.

        Args:
            address: Bluetooth MAC address of the device.

        Returns:
            Dict with 'success' boolean.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "bluetoothctl", "remove", address,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
            return {"success": proc.returncode == 0}
        except Exception as e:
            logger.error("Error removing device %s: %s", address, e)
            return {"success": False, "error": str(e)}
