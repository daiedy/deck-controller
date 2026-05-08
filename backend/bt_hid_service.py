"""Bluetooth HID service for gamepad emulation via BlueZ D-Bus and L2CAP sockets."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import subprocess
from typing import Any, Optional

logger = logging.getLogger("deck-controller.bt_hid_service")

# BlueZ D-Bus constants
BLUEZ_BUS_NAME = "org.bluez"
BLUEZ_ADAPTER_IFACE = "org.bluez.Adapter1"
BLUEZ_DEVICE_IFACE = "org.bluez.Device1"
BLUEZ_AGENT_IFACE = "org.bluez.Agent1"
BLUEZ_AGENT_MANAGER_IFACE = "org.bluez.AgentManager1"
BLUEZ_PROFILE_MANAGER_IFACE = "org.bluez.ProfileManager1"

# L2CAP PSM channels
PSM_CONTROL = 17  # HID Control channel
PSM_INTERRUPT = 19  # HID Interrupt channel

# Bluetooth socket constants
BTPROTO_L2CAP = 0


class ConnectionInfo:
    """Information about a connected Bluetooth device."""

    def __init__(self, address: str, name: str = "Unknown") -> None:
        self.address = address
        self.name = name

    def to_dict(self) -> dict[str, str]:
        """Serialize to dict for RPC transport."""
        return {"address": self.address, "name": self.name}


class BTHIDService:
    """Bluetooth HID gamepad service.

    Manages BlueZ adapter via D-Bus, registers SDP records, opens L2CAP
    sockets for HID control and interrupt channels, and handles pairing.
    """

    def __init__(self, adapter_path: str = "/org/bluez/hci0") -> None:
        self._adapter_path = adapter_path
        self._control_socket: Optional[socket.socket] = None
        self._interrupt_socket: Optional[socket.socket] = None
        self._control_client: Optional[socket.socket] = None
        self._interrupt_client: Optional[socket.socket] = None
        self._connected_device: Optional[ConnectionInfo] = None
        self._running: bool = False
        self._accept_task: Optional[asyncio.Task[None]] = None
        self._original_bluetoothd_args: Optional[str] = None
        self._sdp_record: str = ""
        self._discoverable_before: bool = False

    def _load_sdp_record(self) -> str:
        """Load SDP service record XML from assets."""
        sdp_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets",
            "gamepad_sdp.xml",
        )
        try:
            with open(sdp_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            logger.error("SDP record file not found: %s", sdp_path)
            return ""

    async def _restart_bluetoothd_with_plugin_flag(self) -> bool:
        """Restart bluetoothd with -P input to disable the input plugin.

        The BlueZ input plugin conflicts with HID device emulation.
        We need to disable it so we can manage HID ourselves.

        Returns:
            True if restart was successful.
        """
        try:
            # Save current bluetoothd command line
            proc = await asyncio.create_subprocess_exec(
                "ps",
                "-eo",
                "args",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            for line in stdout.decode().splitlines():
                if "bluetoothd" in line and "grep" not in line:
                    self._original_bluetoothd_args = line.strip()
                    break

            # Stop bluetoothd
            proc = await asyncio.create_subprocess_exec(
                "systemctl",
                "stop",
                "bluetooth",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)

            # Restart with -P input flag
            await asyncio.create_subprocess_exec(
                "/usr/lib/bluetooth/bluetoothd",
                "-P",
                "input",
                "--nodetach",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

            # Wait for bluetoothd to start
            for _ in range(10):
                proc = await asyncio.create_subprocess_exec(
                    "bluetoothctl",
                    "show",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
                if proc.returncode == 0:
                    logger.info("bluetoothd restarted with -P input")
                    return True
                await asyncio.sleep(0.5)

            logger.error("bluetoothd failed to start after restart")
            return False

        except (OSError, asyncio.TimeoutError) as e:
            logger.error("Failed to restart bluetoothd: %s", e)
            return False

    def _restore_bluetoothd(self) -> None:
        """Restore bluetoothd to its original state."""
        try:
            # Kill our custom bluetoothd
            subprocess.run(
                ["pkill", "-f", "bluetoothd.*-P input"],
                capture_output=True,
                timeout=5,
            )
            # Restart the systemd service
            subprocess.run(
                ["systemctl", "start", "bluetooth"],
                capture_output=True,
                timeout=10,
            )
            logger.info("bluetoothd restored to original state")
        except (subprocess.SubprocessError, OSError) as e:
            logger.error("Failed to restore bluetoothd: %s", e)

    def _set_adapter_property(self, prop: str, value: Any) -> bool:
        """Set a BlueZ adapter property via bluetoothctl.

        Args:
            prop: Property name (e.g., 'discoverable', 'pairable', 'alias').
            value: Property value.

        Returns:
            True if successful.
        """
        try:
            if prop == "alias":
                cmd = ["bluetoothctl", "system-alias", str(value)]
            elif prop == "discoverable":
                cmd = ["bluetoothctl", "discoverable", "on" if value else "off"]
            elif prop == "pairable":
                cmd = ["bluetoothctl", "pairable", "on" if value else "off"]
            else:
                cmd = ["bluetoothctl", prop, str(value)]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except (subprocess.SubprocessError, OSError) as e:
            logger.error("Failed to set adapter %s=%s: %s", prop, value, e)
            return False

    def _set_device_class(self, device_class: str) -> bool:
        """Set Bluetooth device class to gamepad.

        Args:
            device_class: Device class hex string (e.g., '0x002508').

        Returns:
            True if successful.
        """
        try:
            result = subprocess.run(
                ["hciconfig", "hci0", "class", device_class],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                logger.info("Set device class to %s", device_class)
                return True
            logger.error("hciconfig class failed: %s", result.stderr)
            return False
        except (subprocess.SubprocessError, OSError) as e:
            logger.error("Failed to set device class: %s", e)
            return False

    def _register_sdp_record(self) -> bool:
        """Register the SDP service record via sdptool using the XML record."""
        sdp_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets",
            "gamepad_sdp.xml",
        )
        if not os.path.isfile(sdp_path):
            logger.error("SDP record file not found: %s", sdp_path)
            return False

        try:
            result = subprocess.run(
                ["sdptool", "add", "--handle=0x10001", "--channel=17"],
                input=self._load_sdp_record(),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                # Fallback: register via XML file directly
                result = subprocess.run(
                    ["sdptool", "add", "--handle=0x10001", "HID"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            logger.info("SDP record registered")
            return True
        except (subprocess.SubprocessError, OSError) as e:
            logger.error("Failed to register SDP record: %s", e)
            return False

    def _open_l2cap_sockets(self) -> bool:
        """Open L2CAP server sockets for HID control and interrupt channels.

        Returns:
            True if both sockets were opened successfully.
        """
        try:
            self._control_socket = socket.socket(
                socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, BTPROTO_L2CAP
            )
            self._control_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._control_socket.bind((socket.BDADDR_ANY, PSM_CONTROL))
            self._control_socket.listen(1)
            self._control_socket.setblocking(False)

            self._interrupt_socket = socket.socket(
                socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, BTPROTO_L2CAP
            )
            self._interrupt_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._interrupt_socket.bind((socket.BDADDR_ANY, PSM_INTERRUPT))
            self._interrupt_socket.listen(1)
            self._interrupt_socket.setblocking(False)

            logger.info("L2CAP sockets opened on PSM %d and %d", PSM_CONTROL, PSM_INTERRUPT)
            return True
        except OSError as e:
            logger.error("Failed to open L2CAP sockets: %s", e)
            self._close_sockets()
            return False

    def _close_sockets(self) -> None:
        """Close all open sockets."""
        for sock_name in (
            "_control_client",
            "_interrupt_client",
            "_control_socket",
            "_interrupt_socket",
        ):
            sock = getattr(self, sock_name, None)
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
                setattr(self, sock_name, None)

    async def start(
        self, controller_name: str = "Deck Controller", device_class: str = "0x002508"
    ) -> bool:
        """Start the Bluetooth HID service.

        Restarts bluetoothd, configures the adapter, registers SDP,
        opens L2CAP sockets, and begins accepting connections.

        Args:
            controller_name: Advertised Bluetooth name.
            device_class: Bluetooth device class (gamepad default).

        Returns:
            True if service started successfully.
        """
        if self._running:
            logger.warning("BT HID service already running")
            return False

        logger.info("Starting BT HID service as '%s'", controller_name)

        # Restart bluetoothd with input plugin disabled
        if not await self._restart_bluetoothd_with_plugin_flag():
            logger.error("Could not restart bluetoothd")
            return False

        # Configure adapter
        self._set_device_class(device_class)
        self._set_adapter_property("alias", controller_name)
        self._set_adapter_property("discoverable", True)
        self._set_adapter_property("pairable", True)

        # Set discoverable timeout to 0 (infinite)
        try:
            subprocess.run(
                ["bluetoothctl", "discoverable-timeout", "0"],
                capture_output=True,
                timeout=5,
            )
        except (subprocess.SubprocessError, OSError):
            pass

        # Register SDP record
        self._register_sdp_record()

        # Open L2CAP sockets
        if not self._open_l2cap_sockets():
            self._restore_bluetoothd()
            return False

        # Register pairing agent (NoInputNoOutput for PIN-less pairing)
        try:
            subprocess.run(
                ["bluetoothctl", "agent", "NoInputNoOutput"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            subprocess.run(
                ["bluetoothctl", "default-agent"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (subprocess.SubprocessError, OSError):
            logger.warning("Could not register pairing agent")

        self._running = True
        self._accept_task = asyncio.create_task(self._accept_connections())
        logger.info("BT HID service started")
        return True

    async def stop(self) -> None:
        """Stop the Bluetooth HID service and clean up."""
        self._running = False

        if self._accept_task is not None:
            self._accept_task.cancel()
            try:
                await self._accept_task
            except asyncio.CancelledError:
                pass
            self._accept_task = None

        self._close_sockets()
        self._connected_device = None

        # Restore adapter state
        self._set_adapter_property("discoverable", False)

        # Restore bluetoothd
        self._restore_bluetoothd()

        logger.info("BT HID service stopped")

    async def _accept_connections(self) -> None:
        """Accept incoming L2CAP connections on both channels."""
        loop = asyncio.get_event_loop()

        while self._running:
            try:
                if self._control_socket is None or self._interrupt_socket is None:
                    break

                # Accept control channel
                logger.info("Waiting for control channel connection...")
                self._control_client, ctrl_addr = await loop.sock_accept(self._control_socket)
                logger.info("Control channel connected from %s", ctrl_addr)

                # Accept interrupt channel
                logger.info("Waiting for interrupt channel connection...")
                self._interrupt_client, intr_addr = await loop.sock_accept(self._interrupt_socket)
                logger.info("Interrupt channel connected from %s", intr_addr)

                # Get device name
                address = ctrl_addr[0] if isinstance(ctrl_addr, tuple) else str(ctrl_addr)
                device_name = self._get_device_name(address)
                self._connected_device = ConnectionInfo(address=address, name=device_name)

                logger.info("Device connected: %s (%s)", device_name, address)

                # Keep connection alive
                while self._running and self._interrupt_client is not None:
                    await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                raise
            except OSError as e:
                if self._running:
                    logger.error("Connection accept error: %s", e)
                    await asyncio.sleep(1)

    def _get_device_name(self, address: str) -> str:
        """Get the friendly name of a Bluetooth device by address."""
        try:
            result = subprocess.run(
                ["bluetoothctl", "info", address],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if "Name:" in line:
                    return line.split("Name:")[1].strip()
        except (subprocess.SubprocessError, OSError):
            pass
        return "Unknown"

    def send_report(self, report: bytes) -> bool:
        """Send an HID report on the interrupt channel.

        Args:
            report: Packed HID report bytes.

        Returns:
            True if sent successfully.
        """
        if self._interrupt_client is None:
            return False

        try:
            # HID data header: 0xA1 = DATA | INPUT
            self._interrupt_client.send(b"\xa1" + report)
            return True
        except OSError as e:
            logger.error("Failed to send HID report: %s", e)
            self._handle_disconnect()
            return False

    def _handle_disconnect(self) -> None:
        """Handle device disconnection."""
        logger.info("Device disconnected")
        for attr in ("_control_client", "_interrupt_client"):
            sock = getattr(self, attr, None)
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
                setattr(self, attr, None)
        self._connected_device = None

    def get_status(self) -> dict[str, Any]:
        """Get current service status.

        Returns:
            Dict with state, connected_device info, and running flag.
        """
        if not self._running:
            state = "idle"
        elif self._connected_device is not None:
            state = "connected"
        else:
            state = "broadcasting"

        return {
            "state": state,
            "running": self._running,
            "connected_device": (
                self._connected_device.to_dict() if self._connected_device else None
            ),
        }

    def get_paired_devices(self) -> list[dict[str, str]]:
        """Get list of paired Bluetooth devices.

        Returns:
            List of dicts with 'address' and 'name' for each paired device.
        """
        devices: list[dict[str, str]] = []
        try:
            result = subprocess.run(
                ["bluetoothctl", "devices", "Paired"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                parts = line.strip().split(" ", 2)
                if len(parts) >= 3 and parts[0] == "Device":
                    devices.append(
                        {
                            "address": parts[1],
                            "name": parts[2],
                        }
                    )
        except (subprocess.SubprocessError, OSError) as e:
            logger.error("Failed to list paired devices: %s", e)
        return devices

    @property
    def is_connected(self) -> bool:
        """Whether a device is currently connected."""
        return self._connected_device is not None

    @property
    def connected_device(self) -> Optional[ConnectionInfo]:
        """Information about the currently connected device."""
        return self._connected_device
