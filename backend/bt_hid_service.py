"""Bluetooth HID service for gamepad emulation via BlueZ D-Bus and L2CAP sockets."""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.util
import fcntl
import logging
import os
import pty
import select as _select_mod
import socket
import struct
import subprocess
import textwrap
import threading
import time as _time_mod
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

# Bluetooth socket constants — use numeric values since DeckyLoader's bundled
# Python may not have socket.AF_BLUETOOTH compiled in
AF_BLUETOOTH = 31
BTPROTO_L2CAP = 0
SOCK_SEQPACKET = 5

# Bluetooth socket options for low-latency HID
SOL_BLUETOOTH = 274
BT_POWER = 9
BT_POWER_FORCE_ACTIVE_OFF = 0
BT_POWER_FORCE_ACTIVE_ON = 1
SO_PRIORITY = 12
L2CAP_OPTIONS = 0x01
SOL_L2CAP = 6

# --- ctypes L2CAP helpers ---------------------------------------------------
# DeckyLoader bundles Python 3.11 via PyInstaller, compiled WITHOUT Bluetooth
# socket support. socket.socket(AF_BLUETOOTH) creates the fd OK (kernel call),
# but bind()/accept() fail because CPython's getsockaddrarg/makesockaddr don't
# know how to pack/unpack sockaddr_l2. We bypass this with direct libc calls.

_libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)


def _check_libc(ret: int, msg: str) -> int:
    """Raise OSError if libc call returned < 0."""
    if ret < 0:
        errno = ctypes.get_errno()
        raise OSError(errno, f"{msg}: {os.strerror(errno)}")
    return ret


def _l2cap_socket() -> int:
    """Create an L2CAP SEQPACKET socket, return raw fd."""
    fd = _libc.socket(AF_BLUETOOTH, SOCK_SEQPACKET, BTPROTO_L2CAP)
    return _check_libc(fd, "socket()")


def _l2cap_setsockopt_reuse(fd: int) -> None:
    """Set SO_REUSEADDR on a socket fd."""
    val = ctypes.c_int(1)
    _check_libc(
        _libc.setsockopt(
            fd, socket.SOL_SOCKET, socket.SO_REUSEADDR, ctypes.byref(val), ctypes.sizeof(val)
        ),
        "setsockopt(SO_REUSEADDR)",
    )


def _l2cap_bind(fd: int, psm: int) -> None:
    """Bind L2CAP socket to BDADDR_ANY:psm.

    struct sockaddr_l2 {
        sa_family_t  l2_family;      // 2 bytes
        unsigned short l2_psm;       // 2 bytes, little-endian
        bdaddr_t     l2_bdaddr;      // 6 bytes
        unsigned short l2_cid;       // 2 bytes
        uint8_t      l2_bdaddr_type; // 1 byte
    };  // total 14 bytes (may be padded)
    """
    addr = struct.pack("<HH6sHB", AF_BLUETOOTH, psm, b"\x00" * 6, 0, 0)
    buf = ctypes.create_string_buffer(addr)
    _check_libc(_libc.bind(fd, buf, len(addr)), "bind()")


def _l2cap_listen(fd: int, backlog: int = 1) -> None:
    _check_libc(_libc.listen(fd, backlog), "listen()")


def _l2cap_set_nonblock(fd: int) -> None:
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)


def _l2cap_set_blocking(fd: int) -> None:
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)


def _l2cap_accept(fd: int) -> tuple[int, str]:
    """Accept a connection, return (new_fd, bdaddr_string).

    Raises BlockingIOError (EAGAIN) if non-blocking and no pending connection.
    """
    addr = ctypes.create_string_buffer(14)
    addrlen = ctypes.c_int(14)
    new_fd = _libc.accept(fd, addr, ctypes.byref(addrlen))
    _check_libc(new_fd, "accept()")
    # Parse bdaddr from offset 4, 6 bytes, reversed (BlueZ convention)
    raw = addr.raw[4:10]
    bdaddr = ":".join(f"{b:02X}" for b in reversed(raw))
    return new_fd, bdaddr


async def _l2cap_async_accept(fd: int) -> tuple[int, str]:
    """Async wrapper: wait for connection using a background thread.

    asyncio.add_reader() doesn't work in DeckyLoader's PyInstaller sandbox,
    so we poll with select() in a thread pool executor.
    """
    loop = asyncio.get_event_loop()

    def _poll_and_accept() -> tuple[int, str]:
        while True:
            ready, _, _ = _select_mod.select([fd], [], [], 1.0)
            if ready:
                return _l2cap_accept(fd)

    return await loop.run_in_executor(None, _poll_and_accept)


def _l2cap_connect(bdaddr: str, psm: int) -> int:
    """Create L2CAP socket and connect to remote bdaddr:psm.

    Returns the connected fd.
    """
    fd = _l2cap_socket()
    try:
        # Pack remote sockaddr_l2
        addr_bytes = bytes(int(x, 16) for x in reversed(bdaddr.split(":")))
        addr = struct.pack("<HH6sHB", AF_BLUETOOTH, psm, addr_bytes, 0, 0)
        buf = ctypes.create_string_buffer(addr)
        _check_libc(_libc.connect(fd, buf, len(addr)), f"connect({bdaddr}:{psm})")
        return fd
    except OSError:
        os.close(fd)
        raise


async def _l2cap_async_connect(bdaddr: str, psm: int) -> int:
    """Async L2CAP connect using a background thread with select().

    asyncio.add_writer() doesn't work in DeckyLoader's PyInstaller sandbox,
    so we do a non-blocking connect + select() in a thread pool executor.
    """
    loop = asyncio.get_event_loop()

    def _connect_thread() -> int:
        fd = _l2cap_socket()
        _l2cap_set_nonblock(fd)
        addr_bytes = bytes(int(x, 16) for x in reversed(bdaddr.split(":")))
        addr = struct.pack("<HH6sHB", AF_BLUETOOTH, psm, addr_bytes, 0, 0)
        buf = ctypes.create_string_buffer(addr)

        ret = _libc.connect(fd, buf, len(addr))
        if ret < 0:
            err = ctypes.get_errno()
            import errno as errno_mod

            if err != errno_mod.EINPROGRESS:
                os.close(fd)
                raise OSError(err, f"connect({bdaddr}:{psm}): {os.strerror(err)}")

        # Wait for connect completion (socket becomes writable)
        _, writable, _ = _select_mod.select([], [fd], [], 10.0)
        if not writable:
            os.close(fd)
            raise asyncio.TimeoutError(f"connect({bdaddr}:{psm}) timed out")

        # Check SO_ERROR
        sock_err = ctypes.c_int(0)
        errlen = ctypes.c_int(ctypes.sizeof(sock_err))
        _libc.getsockopt(
            fd, socket.SOL_SOCKET, socket.SO_ERROR, ctypes.byref(sock_err), ctypes.byref(errlen)
        )
        if sock_err.value != 0:
            os.close(fd)
            raise OSError(sock_err.value, f"connect({bdaddr}:{psm}): {os.strerror(sock_err.value)}")
        return fd

    return await asyncio.wait_for(loop.run_in_executor(None, _connect_thread), timeout=15)


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
        # Server sockets (raw fds via ctypes — Python socket module lacks AF_BLUETOOTH)
        self._control_fd: Optional[int] = None
        self._interrupt_fd: Optional[int] = None
        # Client connection fds
        self._control_client_fd: Optional[int] = None
        self._interrupt_client_fd: Optional[int] = None
        self._connected_device: Optional[ConnectionInfo] = None
        self._running: bool = False
        self._accept_task: Optional[asyncio.Task[None]] = None
        self._original_bluetoothd_args: Optional[str] = None
        self._sdp_record: str = ""
        self._sdp_proc: Optional[subprocess.Popen] = None
        self._discoverable_before: bool = False
        self._report_count: int = 0
        self._ctrl_reader_task: Optional[asyncio.Task[None]] = None
        self._protocol_ready: bool = False
        self._auto_ready_task: Optional[asyncio.Task[None]] = None
        self._failed_devices: dict[str, int] = {}  # addr -> consecutive failure count
        # Clean env for subprocess calls — PyInstaller sets LD_LIBRARY_PATH
        # to its bundle dir, which breaks system binaries
        self._clean_env = os.environ.copy()
        self._clean_env.pop("LD_LIBRARY_PATH", None)
        self._clean_env.pop("LD_LIBRARY_PATH_ORIG", None)
        # Sender thread — moves blocking os.write() off the asyncio event loop.
        # Uses lock-based atomic state instead of a queue:
        # - Gamepad/motion reports: latest-wins (only newest state matters)
        # - Mouse reports: accumulated deltas (never dropped — every delta counts)
        self._pending_lock: threading.Lock = threading.Lock()
        self._pending_gamepad: Optional[bytes] = None
        self._pending_mouse: list[int] = [0, 0, 0, 0]  # [buttons, dx, dy, wheel]
        self._pending_event: threading.Event = threading.Event()
        self._send_thread: Optional[threading.Thread] = None
        self._send_thread_stop: threading.Event = threading.Event()
        # Unix SEQPACKET socket used to receive connection fds from the BlueZ
        # profile helper via NewConnection.  The helper holds the write end.
        self._ipc_recv: Optional[socket.socket] = None

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

    def _subprocess_run(self, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        """Run subprocess with clean environment (no PyInstaller LD_LIBRARY_PATH)."""
        kwargs.setdefault("env", self._clean_env)
        return subprocess.run(*args, **kwargs)

    _MAIN_CONF_PATH = "/etc/bluetooth/main.conf"
    _MAIN_CONF_BACKUP = "/etc/bluetooth/main.conf.deck-controller-backup"

    def _configure_bluetooth_main_conf(self, device_class: str = "0x002508") -> None:
        """Configure /etc/bluetooth/main.conf for HID gamepad emulation.

        Sets device class, AlwaysPairable, and DiscoverableTimeout so they
        take effect on bluetoothd startup.
        """
        import re

        try:
            with open(self._MAIN_CONF_PATH) as f:
                content = f.read()

            # Backup original if no backup exists yet
            if not os.path.isfile(self._MAIN_CONF_BACKUP):
                with open(self._MAIN_CONF_BACKUP, "w") as f:
                    f.write(content)

            # Set Class (uncomment and replace value)
            content = re.sub(
                r"^#?\s*Class\s*=.*$",
                f"Class = {device_class}",
                content,
                flags=re.MULTILINE,
            )
            # Set AlwaysPairable
            content = re.sub(
                r"^#?\s*AlwaysPairable\s*=.*$",
                "AlwaysPairable = true",
                content,
                flags=re.MULTILINE,
            )
            # Set DiscoverableTimeout to 0 (stay discoverable)
            content = re.sub(
                r"^#?\s*DiscoverableTimeout\s*=.*$",
                "DiscoverableTimeout = 0",
                content,
                flags=re.MULTILINE,
            )

            with open(self._MAIN_CONF_PATH, "w") as f:
                f.write(content)
            logger.info(
                "Configured %s: Class=%s, AlwaysPairable, DiscoverableTimeout=0",
                self._MAIN_CONF_PATH,
                device_class,
            )
        except OSError as e:
            logger.warning("Failed to configure %s: %s", self._MAIN_CONF_PATH, e)

    def _restore_bluetooth_main_conf(self) -> None:
        """Restore /etc/bluetooth/main.conf from backup."""
        try:
            if os.path.isfile(self._MAIN_CONF_BACKUP):
                with open(self._MAIN_CONF_BACKUP) as f:
                    content = f.read()
                with open(self._MAIN_CONF_PATH, "w") as f:
                    f.write(content)
                os.remove(self._MAIN_CONF_BACKUP)
                logger.info("Restored %s from backup", self._MAIN_CONF_PATH)
        except OSError as e:
            logger.warning("Failed to restore %s: %s", self._MAIN_CONF_PATH, e)

    async def _restart_bluetoothd_with_plugin_flag(self, device_class: str = "0x002508") -> bool:
        """Restart bluetoothd with -P input to disable the input plugin.

        The BlueZ input plugin conflicts with HID device emulation.
        Uses a systemd drop-in override so bluetoothd stays D-Bus registered.
        SteamOS has a read-only rootfs, so we temporarily disable it.

        Also configures /etc/bluetooth/main.conf to set the device class,
        AlwaysPairable, and DiscoverableTimeout before restart.

        Returns:
            True if restart was successful.
        """
        override_dir = "/etc/systemd/system/bluetooth.service.d"
        override_file = os.path.join(override_dir, "deck-controller.conf")

        try:

            # Create systemd override to add -P input flag
            override_content = (
                "# Added by Deck Controller plugin\n"
                "[Service]\n"
                "ExecStart=\n"
                "ExecStart=/usr/lib/bluetooth/bluetoothd -d -P input\n"
            )

            # SteamOS has read-only rootfs — temporarily disable it
            await self._run_cmd("steamos-readonly", "disable")

            try:
                # Write override file using Python I/O (not bash, which
                # breaks under PyInstaller due to libreadline conflict)
                os.makedirs(override_dir, exist_ok=True)
                with open(override_file, "w") as f:
                    f.write(override_content)
                # Configure main.conf for device class and pairing defaults
                self._configure_bluetooth_main_conf(device_class)
            finally:
                # Re-enable read-only rootfs
                await self._run_cmd("steamos-readonly", "enable")

            # Reload systemd and restart bluetooth
            await self._run_cmd("systemctl", "daemon-reload")
            await self._run_cmd("systemctl", "restart", "bluetooth")

            # Wait for bluetoothd to become responsive
            for _ in range(10):
                proc = await asyncio.create_subprocess_exec(
                    "bluetoothctl",
                    "show",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
                if proc.returncode == 0:
                    logger.info("bluetoothd restarted with -P input via systemd override")
                    return True
                await asyncio.sleep(0.5)

            logger.error("bluetoothd failed to start after restart")
            return False

        except (OSError, asyncio.TimeoutError) as e:
            logger.error("Failed to restart bluetoothd: %s", e)
            return False

    async def _run_cmd(self, *args: str, timeout: float = 10) -> int:
        """Run a command asynchronously and return its exit code."""
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._clean_env,
        )
        await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0

    def _restore_bluetoothd(self) -> None:
        """Restore bluetoothd to its original state by removing the override."""
        override_file = "/etc/systemd/system/bluetooth.service.d/deck-controller.conf"
        try:
            if os.path.isfile(override_file):
                self._subprocess_run(
                    ["steamos-readonly", "disable"],
                    capture_output=True,
                    timeout=10,
                )
                try:
                    os.remove(override_file)
                finally:
                    self._subprocess_run(
                        ["steamos-readonly", "enable"],
                        capture_output=True,
                        timeout=10,
                    )
                self._subprocess_run(
                    ["systemctl", "daemon-reload"],
                    capture_output=True,
                    timeout=10,
                )
            self._subprocess_run(
                ["steamos-readonly", "disable"],
                capture_output=True,
                timeout=10,
            )
            try:
                self._restore_bluetooth_main_conf()
            finally:
                self._subprocess_run(
                    ["steamos-readonly", "enable"],
                    capture_output=True,
                    timeout=10,
                )
            self._subprocess_run(
                ["systemctl", "restart", "bluetooth"],
                capture_output=True,
                timeout=10,
            )
            logger.info("bluetoothd restored to original state")
        except (subprocess.SubprocessError, OSError) as e:
            logger.error("Failed to restore bluetoothd: %s", e)

    def _set_adapter_property(self, prop: str, value: Any) -> bool:
        """Set a BlueZ adapter property via busctl D-Bus call.

        Uses busctl instead of bluetoothctl for reliability when running
        from DeckyLoader's PyInstaller sandbox.

        Args:
            prop: Property name (e.g., 'discoverable', 'pairable', 'alias').
            value: Property value.

        Returns:
            True if successful.
        """
        # Map property names to D-Bus property names and busctl type signatures
        prop_map: dict[str, tuple[str, str, str]] = {
            "alias": ("Alias", "s", str(value)),
            "discoverable": ("Discoverable", "b", "true" if value else "false"),
            "pairable": ("Pairable", "b", "true" if value else "false"),
            "discoverable-timeout": ("DiscoverableTimeout", "u", str(value)),
        }

        dbus_info = prop_map.get(prop)
        if not dbus_info:
            logger.warning("Unknown adapter property: %s", prop)
            return False

        dbus_name, dbus_type, dbus_value = dbus_info
        try:
            cmd = [
                "busctl",
                "set-property",
                "--system",
                BLUEZ_BUS_NAME,
                self._adapter_path,
                BLUEZ_ADAPTER_IFACE,
                dbus_name,
                dbus_type,
                dbus_value,
            ]
            result = self._subprocess_run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                logger.info("Adapter %s set to %s", prop, value)
                return True
            logger.warning("Failed to set adapter %s=%s: %s", prop, value, result.stderr.strip())
            return False
        except (subprocess.SubprocessError, OSError) as e:
            logger.error("Failed to set adapter %s=%s: %s", prop, value, e)
            return False

    def _set_device_class_mgmt_socket(self, major: int, minor: int) -> bool:
        """Set device class using Bluetooth Management socket directly.

        Bypasses btmgmt which hangs in PyInstaller sandbox.
        Uses the kernel management protocol (BTPROTO_HCI + HCI_CHANNEL_CONTROL).
        """
        BTPROTO_HCI = 1
        HCI_CHANNEL_CONTROL = 3
        HCI_DEV_NONE = 0xFFFF
        MGMT_OP_SET_DEV_CLASS = 0x0020
        hci_index = 0  # hci0

        fd = -1
        try:
            fd = _libc.socket(AF_BLUETOOTH, socket.SOCK_RAW, BTPROTO_HCI)
            if fd < 0:
                logger.warning("Failed to create mgmt socket: %s", os.strerror(ctypes.get_errno()))
                return False

            # struct sockaddr_hci { sa_family_t, hci_dev, hci_channel }
            sockaddr = struct.pack("<HHH", AF_BLUETOOTH, HCI_DEV_NONE, HCI_CHANNEL_CONTROL)
            buf = ctypes.create_string_buffer(sockaddr)
            if _libc.bind(fd, buf, len(sockaddr)) < 0:
                logger.warning("Failed to bind mgmt socket: %s", os.strerror(ctypes.get_errno()))
                return False

            # mgmt_hdr{opcode, index, param_len} + mgmt_cp_set_dev_class{major, minor}
            msg = struct.pack("<HHHBB", MGMT_OP_SET_DEV_CLASS, hci_index, 2, major, minor)
            os.write(fd, msg)

            # Read responses until we get command complete for our opcode
            deadline = _time_mod.monotonic() + 3.0
            while _time_mod.monotonic() < deadline:
                remaining = deadline - _time_mod.monotonic()
                if remaining <= 0:
                    break
                ready, _, _ = _select_mod.select([fd], [], [], min(remaining, 1.0))
                if not ready:
                    continue
                resp = os.read(fd, 4096)
                if len(resp) < 9:
                    continue
                evt_code, _, evt_len = struct.unpack_from("<HHH", resp, 0)
                if evt_code in (0x0001, 0x0002) and evt_len >= 3:
                    cmd_opcode, status = struct.unpack_from("<HB", resp, 6)
                    if cmd_opcode == MGMT_OP_SET_DEV_CLASS:
                        if status == 0:
                            logger.info(
                                "Set device class via mgmt socket: major=%d minor=%d", major, minor
                            )
                            return True
                        logger.warning("Mgmt set class failed: status=%d", status)
                        return False

            logger.warning("Mgmt socket: no response for Set Device Class")
            return False
        except Exception as e:
            logger.warning("Mgmt socket class set failed: %s", e)
            return False
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def _set_device_class(self, device_class: str) -> bool:
        """Set Bluetooth device class to gamepad.

        Args:
            device_class: Device class hex string (e.g., '0x002508').

        Returns:
            True if successful.
        """
        class_val = int(device_class, 16)
        # major = Major Device Class (5 bits, bits 12-8 of CoD)
        # minor = Minor Device Class byte (bits 7-0 of CoD)
        major = (class_val >> 8) & 0x1F
        minor = class_val & 0xFF

        # Try management socket first (works inside PyInstaller sandbox)
        if self._set_device_class_mgmt_socket(major, minor):
            return True
        logger.info("Mgmt socket failed, trying btmgmt...")
        # btmgmt hangs when stdin is not a TTY (/dev/null or pipe).
        # Use a PTY for stdin so btmgmt sees a terminal-like fd.
        cmd = ["btmgmt", "class", str(major), str(minor)]

        for attempt in range(2):
            master_fd, slave_fd = pty.openpty()
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    stdin=slave_fd,
                )
                if result.returncode == 0:
                    logger.info("Set device class to %s via btmgmt", device_class)
                    return True
                logger.warning(
                    "btmgmt class failed (attempt %d): %s", attempt + 1, result.stderr.strip()
                )
            except subprocess.TimeoutExpired:
                logger.warning("btmgmt timed out (attempt %d/2)", attempt + 1)
            except (subprocess.SubprocessError, OSError) as e:
                logger.warning("btmgmt not available: %s — trying dbus", e)
                break
            finally:
                os.close(slave_fd)
                os.close(master_fd)
            if attempt == 0:
                _time_mod.sleep(3)

        # Fallback: set via D-Bus adapter property using dbus-send
        try:
            class_val = int(device_class, 16)
            result = self._subprocess_run(
                [
                    "dbus-send",
                    "--system",
                    "--print-reply",
                    f"--dest={BLUEZ_BUS_NAME}",
                    self._adapter_path,
                    "org.freedesktop.DBus.Properties.Set",
                    f"string:{BLUEZ_ADAPTER_IFACE}",
                    "string:Class",
                    f"variant:uint32:{class_val}",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                logger.info("Set device class to %s via dbus-send", device_class)
                return True
            logger.warning("dbus-send class failed: %s", result.stderr.strip())
            return False
        except (subprocess.SubprocessError, OSError) as e:
            logger.warning("Failed to set device class via dbus-send: %s", e)
            return False

    # Inline Python script executed by *system* python3 (not PyInstaller).
    # Registers a BlueZ Profile1 object via dbus-python and keeps the D-Bus
    # connection alive so that the HID SDP record persists.
    _PROFILE_HELPER_SCRIPT = textwrap.dedent(
        """\
        import sys, signal
        import dbus, dbus.service, dbus.mainloop.glib
        from gi.repository import GLib

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SystemBus()

        # --- HID Profile (keeps SDP record alive) ---
        import os as _os, socket as _socket, syslog as _syslog

        _ipc_fd = int(sys.argv[2]) if len(sys.argv) > 2 else -1

        class Profile(dbus.service.Object):
            IFACE = "org.bluez.Profile1"
            _conn_idx = 0

            @dbus.service.method(IFACE, in_signature="", out_signature="")
            def Release(self):
                loop.quit()

            @dbus.service.method(IFACE, in_signature="oha{sv}", out_signature="")
            def NewConnection(self, path, fd, properties):
                # Take ownership of the fd so it is not auto-closed on return.
                raw_fd = fd.take()
                label = b"C" if Profile._conn_idx == 0 else b"I"
                Profile._conn_idx = (Profile._conn_idx + 1) % 2
                _syslog.syslog(
                    f"deck-controller helper: NewConnection ch={label.decode()} "
                    f"path={path} ipc_fd={_ipc_fd}"
                )
                if _ipc_fd >= 0:
                    try:
                        # Forward fd to main plugin via the socketpair.
                        # fromfd() dups _ipc_fd so we close only the dup.
                        ipc = _socket.fromfd(_ipc_fd, _socket.AF_UNIX, _socket.SOCK_STREAM)
                        try:
                            _socket.send_fds(ipc, [label], [raw_fd])
                        finally:
                            ipc.close()
                    except Exception as exc:
                        _syslog.syslog(f"deck-controller helper: IPC send failed: {exc}")
                try:
                    _os.close(raw_fd)
                except OSError:
                    pass

            @dbus.service.method(IFACE, in_signature="o", out_signature="")
            def RequestDisconnection(self, path):
                Profile._conn_idx = 0

        # --- Pairing Agent (NoInputNoOutput for PIN-less pairing) ---
        class Agent(dbus.service.Object):
            IFACE = "org.bluez.Agent1"
            @dbus.service.method(IFACE, in_signature="", out_signature="")
            def Release(self):
                pass
            @dbus.service.method(IFACE, in_signature="os", out_signature="")
            def AuthorizeService(self, device, uuid):
                pass  # Accept all services
            @dbus.service.method(IFACE, in_signature="o", out_signature="s")
            def RequestPinCode(self, device):
                return "0000"
            @dbus.service.method(IFACE, in_signature="o", out_signature="u")
            def RequestPasskey(self, device):
                return dbus.UInt32(0)
            @dbus.service.method(IFACE, in_signature="ouq", out_signature="")
            def DisplayPasskey(self, device, passkey, entered):
                pass
            @dbus.service.method(IFACE, in_signature="ou", out_signature="")
            def RequestConfirmation(self, device, passkey):
                # Auto-accept — no display on Steam Deck
                pass
            @dbus.service.method(IFACE, in_signature="o", out_signature="")
            def RequestAuthorization(self, device):
                pass  # Auto-accept
            @dbus.service.method(IFACE, in_signature="", out_signature="")
            def Cancel(self):
                pass

        profile = Profile(bus, "/org/bluez/hid")
        agent = Agent(bus, "/org/bluez/hid_agent")

        # Register HID profile
        opts = {
            "Role": dbus.String("server"),
            "RequireAuthentication": dbus.Boolean(False),
            "RequireAuthorization": dbus.Boolean(False),
            "AutoConnect": dbus.Boolean(True),
        }
        sdp = sys.argv[1] if len(sys.argv) > 1 else ""
        if sdp:
            opts["ServiceRecord"] = dbus.String(sdp)
        mgr = dbus.Interface(
            bus.get_object("org.bluez", "/org/bluez"),
            "org.bluez.ProfileManager1",
        )
        mgr.RegisterProfile("/org/bluez/hid",
                            "00001124-0000-1000-8000-00805f9b34fb", opts)

        # Register pairing agent as default
        agent_mgr = dbus.Interface(
            bus.get_object("org.bluez", "/org/bluez"),
            "org.bluez.AgentManager1",
        )
        agent_mgr.RegisterAgent("/org/bluez/hid_agent", "NoInputNoOutput")
        agent_mgr.RequestDefaultAgent("/org/bluez/hid_agent")

        print("REGISTERED", flush=True)
        loop = GLib.MainLoop()
        signal.signal(signal.SIGTERM, lambda *_: loop.quit())
        signal.signal(signal.SIGINT, lambda *_: loop.quit())
        loop.run()
    """
    )

    @staticmethod
    def _kill_stale_helpers() -> None:
        """Kill any leftover profile helper processes from previous runs.

        DeckyLoader may SIGKILL the plugin before _unload() completes,
        leaving the helper alive.  We pkill by the unique D-Bus path it
        registers so we never conflict with the new helper.
        """
        try:
            subprocess.run(
                ["pkill", "-9", "-f", "/org/bluez/hid"],
                timeout=3,
                check=False,
            )
        except (subprocess.SubprocessError, OSError):
            pass

    def _register_sdp_record(self) -> bool:
        """Register the SDP/HID profile via a persistent D-Bus helper.

        BlueZ unregisters profiles when the D-Bus sender disconnects, so
        we spawn a long-lived system-python3 process that holds the
        Profile1 registration alive for the lifetime of the service.
        """
        # Kill any leftover helpers from previous (SIGKILL'd) runs
        self._kill_stale_helpers()

        sdp_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets",
            "gamepad_sdp.xml",
        )

        service_record = ""
        if os.path.isfile(sdp_path):
            with open(sdp_path) as f:
                service_record = f.read()

        try:
            # Create a STREAM socket pair so the helper can send connection
            # fds back to us via NewConnection → SCM_RIGHTS.
            ipc_recv, ipc_send = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            self._ipc_recv = ipc_recv

            cmd = ["/usr/bin/python3", "-c", self._PROFILE_HELPER_SCRIPT]
            if service_record:
                cmd.append(service_record)
            cmd.append(str(ipc_send.fileno()))

            self._sdp_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                pass_fds=(ipc_send.fileno(),),
                env={k: v for k, v in os.environ.items() if not k.startswith(("LD_", "_PYI"))},
            )
            ipc_send.close()  # Main process doesn't need the send end

            # Wait for the helper to print REGISTERED (up to 5s)
            import selectors

            sel = selectors.DefaultSelector()
            stdout = self._sdp_proc.stdout
            assert stdout is not None, "SDP helper stdout is None"
            sel.register(stdout, selectors.EVENT_READ)
            ready = sel.select(timeout=5)
            sel.close()
            if ready:
                line = stdout.readline().decode().strip()
                if line == "REGISTERED":
                    logger.info(
                        "HID profile registered (persistent helper pid=%d)", self._sdp_proc.pid
                    )
                    return True
            # Helper didn't respond or crashed
            stderr = ""
            if self._sdp_proc.poll() is not None:
                stderr_pipe = self._sdp_proc.stderr
                stderr = (stderr_pipe.read() if stderr_pipe is not None else b"").decode().strip()
            logger.warning("SDP helper failed: %s", stderr or "timeout")
            self._kill_sdp_helper()
            if self._ipc_recv is not None:
                self._ipc_recv.close()
                self._ipc_recv = None
            return False
        except (subprocess.SubprocessError, OSError) as e:
            logger.warning("Failed to start SDP helper: %s", e)
            if self._ipc_recv is not None:
                self._ipc_recv.close()
                self._ipc_recv = None
            return False

    def _kill_sdp_helper(self) -> None:
        """Terminate the persistent SDP profile helper process."""
        proc = getattr(self, "_sdp_proc", None)
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            logger.info("SDP helper process terminated")
        self._sdp_proc = None

    def _open_l2cap_sockets(self) -> bool:
        """Open L2CAP server sockets for HID control and interrupt channels.

        Uses ctypes to bypass Python socket module's lack of AF_BLUETOOTH.

        Returns:
            True if both sockets were opened successfully.
        """
        try:
            self._control_fd = _l2cap_socket()
            _l2cap_setsockopt_reuse(self._control_fd)
            _l2cap_bind(self._control_fd, PSM_CONTROL)
            _l2cap_listen(self._control_fd)
            _l2cap_set_nonblock(self._control_fd)

            self._interrupt_fd = _l2cap_socket()
            _l2cap_setsockopt_reuse(self._interrupt_fd)
            _l2cap_bind(self._interrupt_fd, PSM_INTERRUPT)
            _l2cap_listen(self._interrupt_fd)
            _l2cap_set_nonblock(self._interrupt_fd)

            logger.info("L2CAP sockets opened on PSM %d and %d", PSM_CONTROL, PSM_INTERRUPT)
            return True
        except OSError as e:
            logger.error("Failed to open L2CAP sockets: %s", e)
            self._close_sockets()
            return False

    def _close_sockets(self) -> None:
        """Close all open socket fds."""
        for attr in (
            "_control_client_fd",
            "_interrupt_client_fd",
            "_control_fd",
            "_interrupt_fd",
        ):
            fd = getattr(self, attr, None)
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
                setattr(self, attr, None)

        if self._ipc_recv is not None:
            try:
                self._ipc_recv.close()
            except OSError:
                pass
            self._ipc_recv = None

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
        if not await self._restart_bluetoothd_with_plugin_flag(device_class):
            logger.error("Could not restart bluetoothd")
            return False

        # Wait for bluetoothd to fully initialize after restart.
        # Needs enough time for HCI setup to complete, otherwise
        # mgmt socket Set Dev Class returns INVALID_PARAMS (status=13).
        await asyncio.sleep(6)

        # Configure adapter via D-Bus
        self._set_device_class(device_class)
        self._set_adapter_property("alias", controller_name)
        self._set_adapter_property("discoverable", True)
        self._set_adapter_property("pairable", True)
        self._set_adapter_property("discoverable-timeout", 0)

        # Register SDP record + pairing agent (persistent D-Bus helper)
        self._register_sdp_record()

        # Open L2CAP sockets
        if not self._open_l2cap_sockets():
            self._restore_bluetoothd()
            return False

        # Auto-trust all paired devices so BlueZ allows incoming connections
        self._trust_paired_devices()

        self._running = True

        # --- Diagnostic: verify adapter state after setup ---
        self._log_adapter_diagnostics()

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

        self._stop_sender_thread()
        self._close_sockets()
        self._kill_sdp_helper()
        self._connected_device = None

        # Restore adapter state
        self._set_adapter_property("discoverable", False)

        # Restore bluetoothd
        self._restore_bluetoothd()

        logger.info("BT HID service stopped")

    async def _ipc_recv_fd(self, expected_label: bytes) -> int:
        """Receive a single fd from the BlueZ profile helper via IPC socketpair.

        The helper's NewConnection sends b"C" for control and b"I" for interrupt
        channels, each paired with the corresponding fd via SCM_RIGHTS.  We
        discard mismatched labels so ordering glitches are handled gracefully.

        Args:
            expected_label: b"C" or b"I" to wait for.

        Returns:
            The received file descriptor integer.
        """
        loop = asyncio.get_event_loop()
        ipc = self._ipc_recv
        if ipc is None:
            raise RuntimeError("IPC socket not available")

        while True:
            # recv_fds is blocking — run it in the default thread pool.
            label_data, fds, _flags, _addr = await loop.run_in_executor(
                None, lambda: socket.recv_fds(ipc, 8, 1)
            )
            if not fds:
                continue
            fd = fds[0]
            label = label_data[:1] if label_data else b""
            if label == expected_label:
                logger.info("IPC: received %s fd=%d", label.decode(), fd)
                return fd
            # Wrong label — close and keep waiting
            logger.warning(
                "IPC: unexpected label %r, expected %r — discarding fd", label, expected_label
            )
            try:
                os.close(fd)
            except OSError:
                pass

    async def _accept_connections(self) -> None:
        """Wait for HID host to connect, or reconnect to a paired host.

        Strategy:
        1. First, try accepting incoming L2CAP connections (host-initiated).
           This is the standard flow: host discovers HID device via SDP,
           then connects L2CAP control (PSM 17) and interrupt (PSM 19).
        2. If no incoming connection within timeout AND a paired device is
           already connected at ACL level, try outgoing L2CAP (reconnect).

        macOS, Windows, and iOS typically initiate the L2CAP connections
        to the HID device after pairing.
        """
        while self._running:
            try:
                connected = False

                # --- Phase 1: Try accepting incoming connections (preferred) ---
                if self._control_fd is not None or self._ipc_recv is not None:
                    try:
                        logger.info("Waiting for host to connect L2CAP (15s)...")

                        # Run raw-socket accept and IPC fd-receive concurrently.
                        # BlueZ 5.7x may route incoming L2CAP through NewConnection
                        # (IPC path) instead of our bound raw socket.
                        raw_task: Optional[asyncio.Task[tuple[int, str]]] = None
                        ipc_ctrl_task: Optional[asyncio.Task[int]] = None

                        if self._control_fd is not None:
                            raw_task = asyncio.ensure_future(_l2cap_async_accept(self._control_fd))
                        if self._ipc_recv is not None:
                            ipc_ctrl_task = asyncio.ensure_future(self._ipc_recv_fd(b"C"))

                        tasks: list[asyncio.Task[Any]] = [
                            t for t in (raw_task, ipc_ctrl_task) if t is not None
                        ]
                        done, pending = await asyncio.wait_for(
                            asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED),
                            timeout=15.0,
                        )

                        for task in pending:
                            task.cancel()
                            try:
                                await task
                            except (asyncio.CancelledError, Exception):
                                pass

                        # Determine which path succeeded
                        ctrl_addr = "unknown"
                        if raw_task is not None and raw_task in done and not raw_task.cancelled():
                            exc = raw_task.exception()
                            if exc is None:
                                self._control_client_fd, ctrl_addr = raw_task.result()
                                logger.info(
                                    "Control channel accepted (raw socket) from %s", ctrl_addr
                                )
                                # Also accept interrupt via raw socket
                                intr_fd, intr_addr = await asyncio.wait_for(
                                    _l2cap_async_accept(self._interrupt_fd or 0), timeout=10.0
                                )
                                self._interrupt_client_fd = intr_fd
                                logger.info("Interrupt channel accepted from %s", intr_addr)
                                device_name = self._get_device_name(ctrl_addr)
                                self._connected_device = ConnectionInfo(
                                    address=ctrl_addr, name=device_name
                                )
                                logger.info(
                                    "Device connected (raw accept): %s (%s)",
                                    device_name,
                                    ctrl_addr,
                                )
                                connected = True

                        elif (
                            ipc_ctrl_task is not None
                            and ipc_ctrl_task in done
                            and not ipc_ctrl_task.cancelled()
                            and ipc_ctrl_task.exception() is None
                        ):
                            # Control fd came via BlueZ NewConnection
                            ctrl_fd = ipc_ctrl_task.result()
                            self._control_client_fd = ctrl_fd
                            logger.info("Control channel received from BlueZ NewConnection")
                            # Wait for interrupt fd via IPC
                            intr_fd = await asyncio.wait_for(self._ipc_recv_fd(b"I"), timeout=10.0)
                            self._interrupt_client_fd = intr_fd
                            logger.info("Interrupt channel received from BlueZ NewConnection")
                            # Non-blocking mode for direct-write mouse path
                            _l2cap_set_nonblock(self._interrupt_client_fd)
                            device_name = "Android"
                            self._connected_device = ConnectionInfo(
                                address=ctrl_addr, name=device_name
                            )
                            logger.info("Device connected (BlueZ NewConnection): %s", device_name)
                            connected = True

                    except asyncio.TimeoutError:
                        logger.info("Accept timeout (15s) — no incoming L2CAP from host")

                # --- Phase 2: Try outgoing reconnection to paired host ---
                if not connected:
                    target = self._find_connected_paired_device()
                    if target:
                        logger.info(
                            "Found paired+connected host: %s — connecting HID channels", target
                        )
                        if await self._connect_hid_channels(target):
                            device_name = self._get_device_name(target)
                            self._connected_device = ConnectionInfo(
                                address=target, name=device_name
                            )
                            logger.info("HID channels connected to %s (%s)", device_name, target)
                            self._failed_devices.pop(target, None)
                            connected = True
                        else:
                            self._failed_devices[target] = self._failed_devices.get(target, 0) + 1
                            fail_count = self._failed_devices[target]
                            logger.info(
                                "Outgoing connect failed for %s (%d consecutive failures)",
                                target,
                                fail_count,
                            )
                            # Exponential backoff: 2s, 4s, 8s, max 30s
                            if fail_count >= 3:
                                backoff = min(2**fail_count, 30)
                                logger.info("Backing off %ds before retry", backoff)
                                await asyncio.sleep(backoff)

                if not connected:
                    await asyncio.sleep(2)
                    continue

                # --- Connected: verify socket health ---
                if not self._log_connection_diagnostics():
                    logger.warning("Connection dead on arrival (SO_ERROR/getpeername) — retrying")
                    self._close_client_fds()
                    self._connected_device = None
                    await asyncio.sleep(2)
                    continue
                self._optimize_socket_latency()

                self._report_count = 0
                self._protocol_ready = False

                # Start the dedicated sender thread — keeps blocking os.write()
                # off the asyncio event loop so trackpad/mouse at 250 Hz never
                # stalls event processing.
                self._start_sender_thread()

                self._ctrl_reader_task = asyncio.create_task(self._control_channel_reader())

                # Auto-enable reports after 2s if host doesn't send SET_PROTOCOL
                async def _auto_ready() -> None:
                    await asyncio.sleep(2.0)
                    if not self._protocol_ready:
                        logger.info("Auto-enabling reports (SET_PROTOCOL timeout)")
                        self._protocol_ready = True

                self._auto_ready_task = asyncio.create_task(_auto_ready())

                # Keep connection alive
                while self._running and self._interrupt_client_fd is not None:
                    await asyncio.sleep(0.5)

                for cleanup_task in ("_ctrl_reader_task", "_auto_ready_task"):
                    task2: Optional[asyncio.Task[Any]] = getattr(self, cleanup_task, None)
                    if task2 is not None:
                        task2.cancel()
                        try:
                            await task2
                        except asyncio.CancelledError:
                            pass
                        setattr(self, cleanup_task, None)

                self._stop_sender_thread()
                self._protocol_ready = False
                logger.info("HID connection lost, waiting 3s before reconnect")
                await asyncio.sleep(3)

            except asyncio.CancelledError:
                raise
            except OSError as e:
                if self._running:
                    logger.error("Connection error: %s", e)
                    self._close_client_fds()
                    await asyncio.sleep(2)

    def _log_adapter_diagnostics(self) -> None:
        """Log full adapter state for debugging."""
        try:
            # btmgmt needs a TTY-like stdin to avoid hanging
            _m, _s = pty.openpty()
            try:
                r = subprocess.run(
                    ["btmgmt", "info"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    stdin=_s,
                )
            finally:
                os.close(_s)
                os.close(_m)
            for line in (r.stdout or "").splitlines():
                if "class" in line.lower():
                    logger.info("DIAG adapter: %s", line.strip())

            # SDP/HID profile
            r2 = self._subprocess_run(
                ["busctl", "tree", "org.bluez"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            hid_lines = [ln for ln in (r2.stdout or "").splitlines() if "hid" in ln.lower()]
            logger.info("DIAG busctl hid entries: %s", hid_lines if hid_lines else "NONE")

            # L2CAP server sockets
            logger.info(
                "DIAG L2CAP server fds: control=%s interrupt=%s",
                self._control_fd,
                self._interrupt_fd,
            )

            # Check if PSM 17/19 are listening
            r3 = self._subprocess_run(
                ["cat", "/proc/net/bluetooth/l2cap"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if r3.returncode == 0:
                for line in (r3.stdout or "").splitlines():
                    if "0011" in line or "0013" in line or "PSM" in line or "src" in line.lower():
                        logger.info("DIAG l2cap: %s", line.strip())
        except Exception as e:
            logger.warning("DIAG error: %s", e)

    def _log_connection_diagnostics(self) -> bool:
        """Log connection state and verify L2CAP channels are alive.

        Returns:
            True if both channels are healthy (SO_ERROR == 0 and getpeername succeeds).
        """
        healthy = True
        try:
            ctrl_fd = self._control_client_fd
            intr_fd = self._interrupt_client_fd
            logger.info("DIAG connected fds: ctrl=%s intr=%s", ctrl_fd, intr_fd)

            # Check socket errors
            for name, fd in [("ctrl", ctrl_fd), ("intr", intr_fd)]:
                if fd is not None:
                    err = ctypes.c_int(0)
                    errlen = ctypes.c_int(ctypes.sizeof(err))
                    _libc.getsockopt(
                        fd,
                        socket.SOL_SOCKET,
                        socket.SO_ERROR,
                        ctypes.byref(err),
                        ctypes.byref(errlen),
                    )
                    logger.info("DIAG %s SO_ERROR=%d", name, err.value)
                    if err.value != 0:
                        healthy = False

            # Check peer address (verifies connection is alive)
            for name, fd in [("ctrl", ctrl_fd), ("intr", intr_fd)]:
                if fd is not None:
                    peer_buf = ctypes.create_string_buffer(14)
                    peer_len = ctypes.c_int(14)
                    ret = _libc.getpeername(fd, peer_buf, ctypes.byref(peer_len))
                    if ret == 0:
                        raw = peer_buf.raw[4:10]
                        peer_addr = ":".join(f"{b:02X}" for b in reversed(raw))
                        logger.info("DIAG %s peer: %s", name, peer_addr)
                    else:
                        logger.info(
                            "DIAG %s getpeername failed: %s", name, os.strerror(ctypes.get_errno())
                        )
                        healthy = False
        except Exception as e:
            logger.warning("DIAG connection check error: %s", e)
            healthy = False
        return healthy

    def _optimize_socket_latency(self) -> None:
        """Apply low-latency socket options to connected L2CAP channels.

        1. BT_POWER force_active — prevents sniff mode, keeping the link in
           active mode so packets are sent immediately without waiting for
           the next sniff window (saves 10-100ms per packet).
        2. SO_PRIORITY 6 — maps to TC_PRIO_INTERACTIVE in the kernel, giving
           BT HID packets scheduling priority over bulk traffic.
        3. L2CAP flush timeout — tells the controller to discard stale packets
           rather than retransmitting them (reduces head-of-line blocking).
        """
        for name, fd in [("ctrl", self._control_client_fd), ("intr", self._interrupt_client_fd)]:
            if fd is None:
                continue

            # Force active power mode (disable sniff)
            try:
                val = ctypes.c_uint8(BT_POWER_FORCE_ACTIVE_ON)
                ret = _libc.setsockopt(
                    fd, SOL_BLUETOOTH, BT_POWER, ctypes.byref(val), ctypes.sizeof(val)
                )
                if ret == 0:
                    logger.info("LOW-LAT %s: BT_POWER force_active set", name)
                else:
                    logger.warning(
                        "LOW-LAT %s: BT_POWER failed: %s", name, os.strerror(ctypes.get_errno())
                    )
            except Exception as e:
                logger.warning("LOW-LAT %s: BT_POWER error: %s", name, e)

            # Set socket priority to interactive
            try:
                prio = ctypes.c_int(6)  # TC_PRIO_INTERACTIVE
                ret = _libc.setsockopt(
                    fd, socket.SOL_SOCKET, SO_PRIORITY, ctypes.byref(prio), ctypes.sizeof(prio)
                )
                if ret == 0:
                    logger.info("LOW-LAT %s: SO_PRIORITY=6 set", name)
                else:
                    logger.warning(
                        "LOW-LAT %s: SO_PRIORITY failed: %s", name, os.strerror(ctypes.get_errno())
                    )
            except Exception as e:
                logger.warning("LOW-LAT %s: SO_PRIORITY error: %s", name, e)

        # Set L2CAP flush timeout on interrupt channel (HID data)
        intr_fd = self._interrupt_client_fd
        if intr_fd is not None:
            try:
                # struct l2cap_options { uint16_t omtu, imtu, flush_to, mode, fcs, ... }
                # We only need to set flush_to (offset 4, 2 bytes).
                # Read current options first
                opts = ctypes.create_string_buffer(32)
                optlen = ctypes.c_int(32)
                ret = _libc.getsockopt(
                    intr_fd, SOL_L2CAP, L2CAP_OPTIONS, opts, ctypes.byref(optlen)
                )
                if ret == 0 and optlen.value >= 6:
                    # Set flush_to to minimum (1 = 0.625ms baseband slots)
                    struct.pack_into("<H", opts, 4, 1)
                    ret = _libc.setsockopt(intr_fd, SOL_L2CAP, L2CAP_OPTIONS, opts, optlen.value)
                    if ret == 0:
                        logger.info("LOW-LAT intr: L2CAP flush_timeout=1 slot")
                    else:
                        logger.warning(
                            "LOW-LAT intr: flush_to setsockopt failed: %s",
                            os.strerror(ctypes.get_errno()),
                        )
                else:
                    logger.warning("LOW-LAT intr: getsockopt L2CAP_OPTIONS failed")
            except Exception as e:
                logger.warning("LOW-LAT intr: flush_timeout error: %s", e)

    def _close_client_fds(self) -> None:
        """Close client connection fds only (keep server sockets)."""
        for attr in ("_control_client_fd", "_interrupt_client_fd"):
            fd = getattr(self, attr, None)
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
                setattr(self, attr, None)

    def _find_connected_paired_device(self) -> Optional[str]:
        """Find a paired Bluetooth device address, preferring connected ones.

        Uses busctl to list devices under /org/bluez/hci0/ and check
        Paired=true.  Returns connected devices first, then any paired device.

        Returns:
            BD address string or None.
        """
        try:
            # List objects under bluez
            result = self._subprocess_run(
                [
                    "busctl",
                    "call",
                    "--system",
                    BLUEZ_BUS_NAME,
                    "/",
                    "org.freedesktop.DBus.ObjectManager",
                    "GetManagedObjects",
                    "",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return None

            # Parse busctl output for device paths
            # Each device path looks like /org/bluez/hci0/dev_XX_XX_XX_XX_XX_XX
            import re

            output = result.stdout
            # Find device paths
            dev_pattern = re.compile(r"/org/bluez/hci0/dev_([0-9A-F_]+)")
            devices = dev_pattern.findall(output)

            paired_addr: Optional[str] = None
            for dev_id in devices:
                addr = dev_id.replace("_", ":")
                dev_path = f"/org/bluez/hci0/dev_{dev_id}"

                # Skip devices that have failed too many times in a row
                if self._failed_devices.get(addr, 0) >= 3:
                    logger.debug("Skipping %s (failed %d times)", addr, self._failed_devices[addr])
                    continue

                # Check Paired
                paired = self._get_device_property_bool(dev_path, "Paired")
                if not paired:
                    continue
                connected = self._get_device_property_bool(dev_path, "Connected")

                if connected:
                    logger.debug("Found paired+connected device: %s", addr)
                    return addr
                if paired_addr is None:
                    paired_addr = addr

            if paired_addr:
                logger.debug("Found paired (not connected) device: %s", paired_addr)
            return paired_addr

        except (subprocess.SubprocessError, OSError) as e:
            logger.debug("Error finding paired devices: %s", e)

        return None

    def _trust_paired_devices(self) -> None:
        """Set Trusted=true on all paired devices so BlueZ allows connections."""
        try:
            result = self._subprocess_run(
                [
                    "busctl",
                    "call",
                    "--system",
                    BLUEZ_BUS_NAME,
                    "/",
                    "org.freedesktop.DBus.ObjectManager",
                    "GetManagedObjects",
                    "",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return
            import re

            dev_pattern = re.compile(r"/org/bluez/hci0/dev_([0-9A-F_]+)")
            for dev_id in dev_pattern.findall(result.stdout):
                dev_path = f"/org/bluez/hci0/dev_{dev_id}"
                if self._get_device_property_bool(dev_path, "Paired"):
                    trusted = self._get_device_property_bool(dev_path, "Trusted")
                    if not trusted:
                        addr = dev_id.replace("_", ":")
                        self._subprocess_run(
                            [
                                "busctl",
                                "set-property",
                                "--system",
                                BLUEZ_BUS_NAME,
                                dev_path,
                                "org.bluez.Device1",
                                "Trusted",
                                "b",
                                "true",
                            ],
                            capture_output=True,
                            text=True,
                            timeout=3,
                        )
                        logger.info("Set Trusted=true for paired device %s", addr)
        except (subprocess.SubprocessError, OSError) as e:
            logger.debug("Error trusting paired devices: %s", e)

    def _get_device_property_bool(self, dev_path: str, prop: str) -> bool:
        """Get a boolean property of a BlueZ device."""
        try:
            result = self._subprocess_run(
                [
                    "busctl",
                    "get-property",
                    "--system",
                    BLUEZ_BUS_NAME,
                    dev_path,
                    "org.bluez.Device1",
                    prop,
                ],
                capture_output=True,
                text=True,
                timeout=3,
            )
            # Output like: b true
            return result.returncode == 0 and "true" in result.stdout.lower()
        except (subprocess.SubprocessError, OSError):
            return False

    async def _connect_hid_channels(self, bdaddr: str) -> bool:
        """Connect outgoing L2CAP HID channels to a paired host.

        Args:
            bdaddr: Remote Bluetooth address.

        Returns:
            True if both channels connected.
        """
        try:
            logger.info("Connecting L2CAP control channel to %s (PSM %d)...", bdaddr, PSM_CONTROL)
            self._control_client_fd = await _l2cap_async_connect(bdaddr, PSM_CONTROL)
            logger.info("Control channel connected")

            logger.info(
                "Connecting L2CAP interrupt channel to %s (PSM %d)...", bdaddr, PSM_INTERRUPT
            )
            self._interrupt_client_fd = await _l2cap_async_connect(bdaddr, PSM_INTERRUPT)
            logger.info("Interrupt channel connected")

            # Non-blocking mode for direct-write mouse path
            _l2cap_set_nonblock(self._interrupt_client_fd)

            # Wait briefly for async errors (Android may RST immediately)
            await asyncio.sleep(0.1)

            # Verify both channels are alive after the brief settle time
            for name, fd in [
                ("ctrl", self._control_client_fd),
                ("intr", self._interrupt_client_fd),
            ]:
                err = ctypes.c_int(0)
                errlen = ctypes.c_int(ctypes.sizeof(err))
                _libc.getsockopt(
                    fd, socket.SOL_SOCKET, socket.SO_ERROR, ctypes.byref(err), ctypes.byref(errlen)
                )
                if err.value != 0:
                    logger.error(
                        "Channel %s dead after connect: SO_ERROR=%d (%s)",
                        name,
                        err.value,
                        os.strerror(err.value),
                    )
                    self._close_client_fds()
                    return False

            return True
        except (OSError, asyncio.TimeoutError) as e:
            logger.error("Failed to connect HID channels to %s: %s", bdaddr, e)
            self._close_client_fds()
            return False

    def _get_device_name(self, address: str) -> str:
        """Get the friendly name of a Bluetooth device by address."""
        try:
            result = self._subprocess_run(
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

    async def _control_channel_reader(self) -> None:
        """Read and respond to HID protocol messages on the control channel.

        macOS (and other hosts) send SET_PROTOCOL, SET_IDLE, GET_REPORT
        on PSM 17 before accepting input data on PSM 19.

        Uses a background thread for blocking reads because
        asyncio.add_reader() doesn't work in DeckyLoader's PyInstaller sandbox.
        """
        if self._control_client_fd is None:
            return

        _l2cap_set_nonblock(self._control_client_fd)
        loop = asyncio.get_event_loop()
        ctrl_queue: asyncio.Queue[bytes] = asyncio.Queue()
        stop_event = threading.Event()
        fd = self._control_client_fd

        def _reader_thread() -> None:
            while not stop_event.is_set() and fd is not None:
                try:
                    data = os.read(fd, 1024)
                    if data:
                        loop.call_soon_threadsafe(ctrl_queue.put_nowait, data)
                    else:
                        loop.call_soon_threadsafe(ctrl_queue.put_nowait, b"")
                        break
                except BlockingIOError:
                    stop_event.wait(0.01)
                except OSError:
                    loop.call_soon_threadsafe(ctrl_queue.put_nowait, b"")
                    break

        thread = threading.Thread(target=_reader_thread, daemon=True, name="ctrl-reader")
        thread.start()
        logger.info("Control channel reader started (threaded)")
        try:
            while self._running:
                data = await ctrl_queue.get()
                if not data:
                    break
                self._handle_control_message(data)
        except asyncio.CancelledError:
            raise
        finally:
            stop_event.set()
            thread.join(timeout=1.0)

    def _handle_control_message(self, data: bytes) -> None:
        """Handle a single HID protocol message on the control channel."""
        if not data:
            return
        header = data[0]
        msg_type = (header >> 4) & 0x0F
        param = header & 0x0F

        logger.info("HID control msg: type=0x%x param=0x%x data=%s", msg_type, param, data.hex())

        if msg_type == 0x07:  # SET_PROTOCOL (boot=0, report=1)
            logger.info("SET_PROTOCOL: %s mode", "report" if param else "boot")
            self._send_control(b"\x00")  # HANDSHAKE(successful)
            if not self._protocol_ready:
                self._protocol_ready = True
                logger.info("Protocol ready — reports enabled")
        elif msg_type == 0x09:  # SET_IDLE
            logger.info("SET_IDLE: rate=%d", param)
            self._send_control(b"\x00")  # HANDSHAKE(successful)
        elif msg_type == 0x06:  # GET_PROTOCOL
            self._send_control(b"\xa0\x01")  # DATA | report protocol
        elif msg_type == 0x04:  # GET_REPORT
            from .hid_descriptor import DPAD_NEUTRAL
            from .hid_descriptor import pack_report as _pack

            report = _pack(0, 0, 0, 0, 0, 0, 0, DPAD_NEUTRAL)
            self._send_control(b"\xa3" + report)
        elif msg_type == 0x05:  # SET_REPORT
            self._send_control(b"\x00")  # HANDSHAKE(successful)
        elif msg_type == 0x01:  # HID_CONTROL (suspend/exit/unplug)
            logger.info("HID_CONTROL: param=0x%x", param)
        else:
            logger.debug("Unknown control msg type 0x%x", msg_type)
            self._send_control(b"\x03")  # HANDSHAKE(err_unsupported)

    def _send_control(self, data: bytes) -> None:
        """Send response on the HID control channel."""
        if self._control_client_fd is not None:
            try:
                os.write(self._control_client_fd, data)
            except OSError as e:
                logger.error("Failed to send control response: %s", e)

    # ------------------------------------------------------------------
    # Sender thread — keeps blocking os.write() off the asyncio event loop
    # ------------------------------------------------------------------

    def _start_sender_thread(self) -> None:
        """Start the background BT sender thread.

        Resets pending state so we don't send stale data from a previous
        connection.
        """
        self._send_thread_stop.clear()
        with self._pending_lock:
            self._pending_gamepad = None
            self._pending_mouse[:] = [0, 0, 0, 0]
        self._pending_event.clear()
        self._send_thread = threading.Thread(
            target=self._sender_thread_func, daemon=True, name="bt-sender"
        )
        self._send_thread.start()
        logger.info("BT sender thread started")

    def _stop_sender_thread(self) -> None:
        """Signal the sender thread to stop and wait for it to exit.

        Must NOT be called from within the sender thread itself.
        """
        self._send_thread_stop.set()
        self._pending_event.set()  # wake the thread so it sees stop flag
        if self._send_thread is not None:
            self._send_thread.join(timeout=2.0)
            self._send_thread = None

    def _sender_thread_func(self) -> None:
        """Sender thread: send pending reports to the interrupt channel.

        Uses lock-based atomic state instead of a FIFO queue:
        - Gamepad reports use latest-wins — only the most recent state is sent.
        - Mouse reports accumulate deltas — no movement is ever lost.
        - threading.Event provides instant wakeup (no polling delay).
        """
        while not self._send_thread_stop.is_set():
            self._pending_event.wait(timeout=0.1)
            if self._send_thread_stop.is_set():
                break
            self._pending_event.clear()

            with self._pending_lock:
                gamepad = self._pending_gamepad
                self._pending_gamepad = None
                mouse = self._pending_mouse[:]
                self._pending_mouse[:] = [0, 0, 0, 0]

            fd = self._interrupt_client_fd
            if fd is None:
                continue

            # Send accumulated mouse deltas first (more latency-sensitive)
            mouse_buttons, mouse_dx, mouse_dy, mouse_wheel = mouse
            if mouse_dx or mouse_dy or mouse_wheel or mouse_buttons:
                clamped_dx = max(-127, min(127, mouse_dx))
                clamped_dy = max(-127, min(127, mouse_dy))
                clamped_wheel = max(-127, min(127, mouse_wheel))
                mouse_report = struct.pack(
                    "<BBbbb",
                    0x02,
                    mouse_buttons & 0x07,
                    clamped_dx,
                    clamped_dy,
                    clamped_wheel,
                )
                if not self._write_hid_report(fd, mouse_report):
                    break
                # If deltas exceeded ±127, keep remainder for next cycle
                rem_dx = mouse_dx - clamped_dx
                rem_dy = mouse_dy - clamped_dy
                rem_wheel = mouse_wheel - clamped_wheel
                if rem_dx or rem_dy or rem_wheel:
                    with self._pending_lock:
                        self._pending_mouse[1] += rem_dx
                        self._pending_mouse[2] += rem_dy
                        self._pending_mouse[3] += rem_wheel
                    self._pending_event.set()

            # Send gamepad/motion report (latest state)
            if gamepad is not None:
                if not self._write_hid_report(fd, gamepad):
                    break

    def _write_hid_report(self, fd: int, report: bytes) -> bool:
        """Write a single HID report to the interrupt channel.

        Handles non-blocking mode: retries with short select() on EAGAIN.
        Returns True on success, False on fatal error (caller should break).
        """
        try:
            payload = b"\xa1" + report
            try:
                os.write(fd, payload)
            except BlockingIOError:
                # Socket buffer full — wait up to 10ms for space
                _, writable, _ = _select_mod.select([], [fd], [], 0.010)
                if writable:
                    os.write(fd, payload)
                else:
                    # Still full — drop this report (gamepad is latest-wins anyway)
                    return True
            self._report_count += 1
            if self._report_count <= 5 or self._report_count % 500 == 0:
                logger.info(
                    "HID report #%d (%d bytes): %s",
                    self._report_count,
                    len(payload),
                    payload[:10].hex(),
                )
            return True
        except OSError as e:
            if e.errno == 11:  # EAGAIN — shouldn't happen after select, but be safe
                return True
            logger.error("Failed to send HID report: %s", e)
            self._handle_disconnect()
            return False

    def send_report(self, report: bytes) -> bool:
        """Submit a gamepad or motion HID report (latest-wins semantics).

        Only the most recent report is kept — if a new report arrives before
        the sender thread processes the previous one, the old one is silently
        replaced.  This is correct for absolute-state reports (gamepad axes,
        buttons, motion sensors) where only the current state matters.

        Args:
            report: Packed HID report bytes.

        Returns:
            True if the report was accepted.
        """
        if self._interrupt_client_fd is None:
            return False
        if not self._protocol_ready:
            return False

        with self._pending_lock:
            self._pending_gamepad = report
        self._pending_event.set()
        return True

    def send_mouse_report(self, buttons: int, dx: int, dy: int, wheel: int) -> bool:
        """Send mouse report with minimal latency (direct-write burst path).

        Writes HID mouse reports directly from the calling thread.  If the
        delta exceeds ±127 (fast swipe), sends multiple back-to-back reports
        immediately rather than deferring remainder to the sender thread.

        If the direct write would block (BT buffer full), drops the remaining
        data for this frame (latest-position-wins — next frame will be fresh).

        Args:
            buttons: 3-bit button bitmask (bit 0=left, 1=right, 2=middle).
            dx: Relative X movement.
            dy: Relative Y movement.
            wheel: Scroll wheel delta.

        Returns:
            True if accepted.
        """
        fd = self._interrupt_client_fd
        if fd is None:
            return False
        if not self._protocol_ready:
            return False

        btn = buttons & 0x07
        rem_dx = dx
        rem_dy = dy
        rem_wheel = wheel

        # Burst: send multiple ±127 reports until delta is consumed
        try:
            while rem_dx or rem_dy or rem_wheel:
                clamped_dx = max(-127, min(127, rem_dx))
                clamped_dy = max(-127, min(127, rem_dy))
                clamped_wheel = max(-127, min(127, rem_wheel))
                report = struct.pack("<BBbbb", 0x02, btn, clamped_dx, clamped_dy, clamped_wheel)
                payload = b"\xa1" + report
                try:
                    os.write(fd, payload)
                except BlockingIOError:
                    # Buffer full — drop remainder (next frame brings fresh data)
                    break
                rem_dx -= clamped_dx
                rem_dy -= clamped_dy
                rem_wheel -= clamped_wheel
                self._report_count += 1
                if self._report_count <= 5 or self._report_count % 500 == 0:
                    logger.info(
                        "HID report #%d (mouse burst) (%d bytes): %s",
                        self._report_count,
                        len(payload),
                        payload[:10].hex(),
                    )
            return True
        except OSError as e:
            if e.errno == 11:  # EAGAIN
                return True
            logger.error("Mouse direct write failed: %s", e)
            self._handle_disconnect()
            return False

    def _handle_disconnect(self) -> None:
        """Handle device disconnection."""
        logger.info("Device disconnected")
        for attr in ("_control_client_fd", "_interrupt_client_fd"):
            fd = getattr(self, attr, None)
            if fd is not None:
                try:
                    os.close(fd)
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
            result = self._subprocess_run(
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
