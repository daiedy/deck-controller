"""Input reader for Steam Deck built-in gamepad.

Reads raw HID reports from /dev/hidraw* (Valve Steam Controller USB HID) as
the primary input source.  This bypasses Steam's virtual Xbox 360 pad at
/dev/input/event8, which only produces events in Gaming mode and is grabbed
by Steam.  Falls back to evdev if no hidraw device is found.

Report format reverse-engineered from SDL2's ``SDL_hidapi_steamdeck.c`` and
Valve's ``controller_structs.h`` (``SteamDeckStatePacket_t``).
"""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.util
import fcntl
import glob
import logging
import os
import select
import struct
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .hid_descriptor import DPAD_NEUTRAL

logger = logging.getLogger("deck-controller.input_reader")

# ---------------------------------------------------------------------------
# hidraw — Valve Steam Deck controller (primary input source)
# ---------------------------------------------------------------------------

VALVE_CONTROLLER_NAME: str = "Valve Software Steam Controller"
VALVE_REPORT_SIZE: int = 64
VALVE_REPORT_VERSION: int = 0x0001
VALVE_DECK_STATE_TYPE: int = 9  # ID_CONTROLLER_DECK_STATE

# Valve ulButtonsL bits (uint32 LE at report offset 8)
_VBL_R2: int = 0x00000001
_VBL_L2: int = 0x00000002
_VBL_R1: int = 0x00000004
_VBL_L1: int = 0x00000008
_VBL_Y: int = 0x00000010
_VBL_B: int = 0x00000020
_VBL_X: int = 0x00000040
_VBL_A: int = 0x00000080
_VBL_DPAD_UP: int = 0x00000100
_VBL_DPAD_RIGHT: int = 0x00000200
_VBL_DPAD_LEFT: int = 0x00000400
_VBL_DPAD_DOWN: int = 0x00000800
_VBL_VIEW: int = 0x00001000  # SELECT
_VBL_STEAM: int = 0x00002000  # HOME
_VBL_MENU: int = 0x00004000  # START
_VBL_L5: int = 0x00008000
_VBL_R5: int = 0x00010000
_VBL_LPAD_CLICK: int = 0x00020000
_VBL_RPAD_CLICK: int = 0x00040000
_VBL_LPAD_TOUCH: int = 0x00080000
_VBL_RPAD_TOUCH: int = 0x00100000
_VBL_L3: int = 0x00400000
_VBL_R3: int = 0x04000000

# Valve ulButtonsH bits (uint32 LE at report offset 12)
_VBH_L4: int = 0x00000200
_VBH_R4: int = 0x00000400

# Map Valve ulButtonsL → InputState button bit position
_VALVE_BTNL_MAP: list[tuple[int, int]] = [
    (_VBL_A, 0),  # A
    (_VBL_B, 1),  # B
    (_VBL_X, 2),  # X
    (_VBL_Y, 3),  # Y
    (_VBL_L1, 4),  # L1
    (_VBL_R1, 5),  # R1
    (_VBL_L2, 6),  # L2 digital
    (_VBL_R2, 7),  # R2 digital
    (_VBL_VIEW, 8),  # SELECT
    (_VBL_MENU, 9),  # START
    (_VBL_L3, 10),  # L3
    (_VBL_R3, 11),  # R3
    (_VBL_STEAM, 12),  # HOME
    (_VBL_L5, 14),  # L5
    (_VBL_R5, 16),  # R5
]

# Map Valve ulButtonsH → InputState button bit position
_VALVE_BTNH_MAP: list[tuple[int, int]] = [
    (_VBH_L4, 13),  # L4
    (_VBH_R4, 15),  # R4
]

# struct format for SteamDeckStatePacket_t payload (offset 4..59)
# unPacketNum(I) ulButtonsL(I) ulButtonsH(I)
# sLeftPadX(h) sLeftPadY(h) sRightPadX(h) sRightPadY(h)
# sAccelX(h) sAccelY(h) sAccelZ(h)
# sGyroX(h) sGyroY(h) sGyroZ(h)
# sGyroQuatW(h) sGyroQuatX(h) sGyroQuatY(h) sGyroQuatZ(h)
# sTriggerRawL(H) sTriggerRawR(H)
# sLeftStickX(h) sLeftStickY(h) sRightStickX(h) sRightStickY(h)
# sPressurePadLeft(H) sPressurePadRight(H)
_DECK_STATE_FMT: str = "<IIIhhhhhhhhhhhhhhHHhhhhHH"

# ---------------------------------------------------------------------------
# evdev fallback constants (from <linux/input-event-codes.h>)
# ---------------------------------------------------------------------------

INPUT_EVENT_FORMAT = "llHHi"
INPUT_EVENT_SIZE = struct.calcsize(INPUT_EVENT_FORMAT)

EV_SYN = 0x00
EV_KEY = 0x01
EV_ABS = 0x03

BTN_A = 0x130
BTN_B = 0x131
BTN_X = 0x133
BTN_Y = 0x134
BTN_TL = 0x136
BTN_TR = 0x137
BTN_TL2 = 0x138
BTN_TR2 = 0x139
BTN_SELECT = 0x13A
BTN_START = 0x13B
BTN_MODE = 0x13C
BTN_THUMBL = 0x13D
BTN_THUMBR = 0x13E
BTN_TRIGGER_HAPPY1 = 0x2C0
BTN_TRIGGER_HAPPY2 = 0x2C1
BTN_TRIGGER_HAPPY3 = 0x2C2
BTN_TRIGGER_HAPPY4 = 0x2C3

ABS_X = 0x00
ABS_Y = 0x01
ABS_Z = 0x02
ABS_RX = 0x03
ABS_RY = 0x04
ABS_RZ = 0x05
ABS_HAT0X = 0x10
ABS_HAT0Y = 0x11
ABS_HAT2X = 0x14
ABS_HAT2Y = 0x15
ABS_HAT3X = 0x16
ABS_HAT3Y = 0x17

EVIOCGNAME_256 = 0x80FF4506
EVIOCGRAB = 0x40044590
EVIOCGBIT_0 = 0x80044520

DECK_CONTROLLER_NAMES: list[str] = [
    "Microsoft X-Box 360 pad",
    "Steam Deck",
    "Valve Software Steam Controller",
]

STICK_MAX: int = 32767
TRIGGER_MAX: int = 255

# ---------------------------------------------------------------------------
# HID driver rebinding — block Steam from accessing controller hidraw
# ---------------------------------------------------------------------------

_UDEV_RULE_PATH: str = "/run/udev/rules.d/99-deck-controller-block.rules"
_UDEV_RULE_CONTENT: str = (
    'ACTION=="add", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="28de", '
    'ATTRS{idProduct}=="1205", MODE="0600", OWNER="root", GROUP="root", '
    'RUN+="/usr/bin/setfacl -b %N"\n'
)
_HID_STEAM_UNBIND: str = "/sys/bus/hid/drivers/hid-steam/unbind"
_HID_STEAM_BIND: str = "/sys/bus/hid/drivers/hid-steam/bind"


def _system_env() -> dict[str, str]:
    """Return a clean copy of os.environ without PyInstaller-injected library paths.

    DeckyLoader runs plugins via PyInstaller, which sets LD_LIBRARY_PATH to its
    temp extraction directory.  System binaries like udevadm link against system
    libcrypto/libsystemd and will fail if they load the bundled version.
    """
    env = os.environ.copy()
    for key in ("LD_LIBRARY_PATH", "LD_PRELOAD"):
        env.pop(key, None)
    return env


_BUTTON_MAP: dict[int, int] = {
    BTN_A: 0,
    BTN_B: 1,
    BTN_X: 2,
    BTN_Y: 3,
    BTN_TL: 4,
    BTN_TR: 5,
    BTN_TL2: 6,
    BTN_TR2: 7,
    BTN_SELECT: 8,
    BTN_START: 9,
    BTN_THUMBL: 10,
    BTN_THUMBR: 11,
    BTN_MODE: 12,
    BTN_TRIGGER_HAPPY1: 13,
    BTN_TRIGGER_HAPPY2: 14,
    BTN_TRIGGER_HAPPY3: 15,
    BTN_TRIGGER_HAPPY4: 16,
}

_DPAD_MAP: dict[tuple[int, int], int] = {
    (0, 0): DPAD_NEUTRAL,
    (0, -1): 0,
    (1, -1): 1,
    (1, 0): 2,
    (1, 1): 3,
    (0, 1): 4,
    (-1, 1): 5,
    (-1, 0): 6,
    (-1, -1): 7,
}


@dataclass
class InputState:
    """Normalized gamepad state."""

    buttons: int = 0
    left_x: int = 0
    left_y: int = 0
    right_x: int = 0
    right_y: int = 0
    l2: int = 0
    r2: int = 0
    dpad: int = DPAD_NEUTRAL

    # Trackpad state (absolute positions, 0-32767)
    trackpad_right_x: int = 0
    trackpad_right_y: int = 0
    trackpad_left_x: int = 0
    trackpad_left_y: int = 0
    trackpad_right_touch: bool = False
    trackpad_left_touch: bool = False
    trackpad_right_click: bool = False
    trackpad_left_click: bool = False

    def copy(self) -> InputState:
        """Create a shallow copy of this state."""
        return InputState(
            buttons=self.buttons,
            left_x=self.left_x,
            left_y=self.left_y,
            right_x=self.right_x,
            right_y=self.right_y,
            l2=self.l2,
            r2=self.r2,
            dpad=self.dpad,
            trackpad_right_x=self.trackpad_right_x,
            trackpad_right_y=self.trackpad_right_y,
            trackpad_left_x=self.trackpad_left_x,
            trackpad_left_y=self.trackpad_left_y,
            trackpad_right_touch=self.trackpad_right_touch,
            trackpad_left_touch=self.trackpad_left_touch,
            trackpad_right_click=self.trackpad_right_click,
            trackpad_left_click=self.trackpad_left_click,
        )


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _get_device_name(fd: int) -> str:
    """Get evdev input device name via ioctl EVIOCGNAME."""
    buf = ctypes.create_string_buffer(256)
    try:
        fcntl.ioctl(fd, EVIOCGNAME_256, buf)
        return buf.value.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _has_ev_abs(fd: int) -> bool:
    """Check if device supports EV_ABS (absolute axes — sticks, triggers)."""
    buf = ctypes.create_string_buffer(4)
    try:
        fcntl.ioctl(fd, EVIOCGBIT_0, buf)
        ev_bits = struct.unpack("<I", buf.raw)[0]
        return bool(ev_bits & (1 << EV_ABS))
    except OSError:
        return False


def _apply_deadzone(value: int, deadzone: float, axis_max: int) -> int:
    """Apply deadzone to an axis value."""
    threshold = int(axis_max * deadzone)
    if abs(value) < threshold:
        return 0
    return value


def _get_hidraw_name(devname: str) -> str:
    """Get HID device name from sysfs for a /dev/hidrawN device."""
    sysfs = f"/sys/class/hidraw/{devname}/device/uevent"
    try:
        with open(sysfs) as f:
            for line in f:
                if line.startswith("HID_NAME="):
                    return line.strip().split("=", 1)[1]
    except OSError:
        pass
    return ""


# ---------------------------------------------------------------------------
# InputReader
# ---------------------------------------------------------------------------


class InputReader:
    """Reads input from Steam Deck's built-in gamepad.

    Primary source: /dev/hidraw* (Valve USB HID, 250 Hz, works alongside Steam).
    Fallback: /dev/input/event* (evdev — only works if device not grabbed).
    """

    def __init__(self, deadzone: float = 0.10) -> None:
        self._fd: Optional[int] = None
        self._dev_path: str = ""
        self._running: bool = False
        self._use_hidraw: bool = False
        self._task: Optional[asyncio.Task[None]] = None
        self._state: InputState = InputState()
        self._deadzone: float = deadzone
        self._callback: Optional[Callable[[InputState], None]] = None
        self._toggle_callback: Optional[Callable[[], None]] = None
        self._gamepad_active: bool = True
        self._grabbed: bool = False
        self._combo_active: bool = False
        self._prev_key_state: Optional[tuple[int, ...]] = None
        # HID device ID for the active hidraw (e.g. "0003:28DE:1205.0005")
        self._hid_device_id: str = ""
        self._steam_blocked: bool = False
        # evdev grab fds — used in hidraw mode to block Steam from reading input
        self._evdev_grab_fds: list[tuple[int, str]] = []
        # evdev state
        self._hat_x: int = 0
        self._hat_y: int = 0
        # Signals reader thread to stop for device swap
        self._reader_stop_event: Optional[threading.Event] = None
        self._device_swapped: bool = False

    # ------------------------------------------------------------------
    # Device discovery
    # ------------------------------------------------------------------

    @staticmethod
    def find_devices() -> list[dict[str, str]]:
        """Find available gamepad devices (hidraw + evdev)."""
        devices: list[dict[str, str]] = []
        # hidraw devices
        for devname in sorted(
            os.listdir("/sys/class/hidraw/") if os.path.isdir("/sys/class/hidraw") else []
        ):
            name = _get_hidraw_name(devname)
            if VALVE_CONTROLLER_NAME in name:
                path = f"/dev/{devname}"
                devices.append({"path": path, "name": name, "phys": "hidraw"})
        # evdev devices (fallback)
        for path in sorted(glob.glob("/dev/input/event*")):
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            try:
                name = _get_device_name(fd)
                for pattern in DECK_CONTROLLER_NAMES:
                    if pattern.lower() in name.lower():
                        if _has_ev_abs(fd):
                            devices.append({"path": path, "name": name, "phys": "evdev"})
                        break
            finally:
                os.close(fd)
        return devices

    def _find_hidraw_device(self) -> Optional[tuple[int, str]]:
        """Find the Valve Steam Controller hidraw device that produces data.

        Steam Deck exposes 3 hidraw interfaces; only one (typically hidraw2)
        actually sends input reports at ~250 Hz.  We open each candidate and
        try a short read to find the active one.
        """
        sysfs = "/sys/class/hidraw"
        if not os.path.isdir(sysfs):
            return None
        for devname in sorted(os.listdir(sysfs)):
            name = _get_hidraw_name(devname)
            if VALVE_CONTROLLER_NAME not in name:
                continue
            path = f"/dev/{devname}"
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError as e:
                logger.debug("Cannot open %s: %s", path, e)
                continue
            # Probe: try reading a report within 100 ms
            got_data = False
            end = time.time() + 0.1
            while time.time() < end:
                try:
                    data = os.read(fd, VALVE_REPORT_SIZE)
                    if len(data) == VALVE_REPORT_SIZE:
                        got_data = True
                        break
                except BlockingIOError:
                    time.sleep(0.005)
            if got_data:
                logger.info("Found Valve controller hidraw: %s", path)
                # Switch from O_NONBLOCK (used for probe) to blocking I/O
                flags = fcntl.fcntl(fd, fcntl.F_GETFL)
                fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
                return fd, path
            os.close(fd)
            logger.debug("Skipping %s (no data in 100 ms)", path)
        return None

    def _find_evdev_device(self) -> Optional[tuple[int, str]]:
        """Find the first matching evdev controller device with gamepad axes."""
        for path in sorted(glob.glob("/dev/input/event*")):
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            name = _get_device_name(fd)
            for pattern in DECK_CONTROLLER_NAMES:
                if pattern.lower() in name.lower():
                    if _has_ev_abs(fd):
                        logger.info("Found evdev controller: %s at %s", name, path)
                        # Switch from O_NONBLOCK (used for detection) to blocking I/O
                        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
                        fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
                        return fd, path
                    break
            os.close(fd)
        return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(
        self,
        callback: Callable[[InputState], None],
        grab: bool = True,
        toggle_callback: Optional[Callable[[], None]] = None,
    ) -> bool:
        """Start reading input.

        Tries hidraw first (works alongside Steam in any mode), falls back
        to evdev.  The *grab* parameter only applies to evdev.
        """
        if self._running:
            logger.warning("Input reader already running")
            return False

        self._callback = callback
        self._toggle_callback = toggle_callback
        self._gamepad_active = True

        # Try hidraw first
        result = self._find_hidraw_device()
        if result is not None:
            self._fd, self._dev_path = result
            self._use_hidraw = True
            self._hid_device_id = self._get_hid_device_id()
            logger.info(
                "Using hidraw input source: %s (HID %s)", self._dev_path, self._hid_device_id
            )
            # Block Steam from accessing controller hidraw
            if grab:
                self._block_steam_input()
        else:
            # Fallback to evdev
            result = self._find_evdev_device()
            if result is None:
                logger.error("No controller device found (hidraw or evdev)")
                return False
            self._fd, self._dev_path = result
            self._use_hidraw = False
            logger.info("Using evdev input source: %s", self._dev_path)
            if grab:
                try:
                    fcntl.ioctl(self._fd, EVIOCGRAB, 1)
                    self._grabbed = True
                    logger.info("Grabbed device exclusively")
                except OSError as e:
                    logger.warning("Could not grab device: %s", e)

        self._running = True
        self._state = InputState()
        self._prev_key_state = None
        self._combo_active = False
        self._task = asyncio.create_task(self._read_loop())
        logger.info("Input reader started (%s)", "hidraw" if self._use_hidraw else "evdev")
        return True

    async def stop(self) -> None:
        """Stop reading input and release the device."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._fd is not None:
            if self._grabbed:
                try:
                    fcntl.ioctl(self._fd, EVIOCGRAB, 0)
                except OSError:
                    pass
                self._grabbed = False
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        # Restore Steam's access to controller
        if self._steam_blocked:
            self._unblock_steam_input()
        self._ungrab_evdev()
        logger.info("Input reader stopped")

    def toggle_grab(self) -> bool:
        """Toggle gamepad forwarding mode.

        For hidraw: blocks/unblocks Steam via HID driver rebinding.
        For evdev: toggles EVIOCGRAB.

        Returns:
            New gamepad_active state.
        """
        if self._use_hidraw:
            self._gamepad_active = not self._gamepad_active
            if self._gamepad_active:
                ok = self._block_steam_input()
                if ok:
                    # Restart reader thread with new fd
                    self._signal_reader_restart()
            else:
                ok = self._unblock_steam_input()
                if ok:
                    # Restart reader thread with new fd
                    self._signal_reader_restart()
            logger.info(
                "Gamepad forwarding %s (steam_blocked=%s)",
                "enabled" if self._gamepad_active else "disabled",
                self._steam_blocked,
            )
            return self._gamepad_active

        if self._fd is None:
            return self._gamepad_active
        if self._grabbed:
            try:
                fcntl.ioctl(self._fd, EVIOCGRAB, 0)
                self._grabbed = False
                self._gamepad_active = False
                logger.info("Device ungrabbed — local input restored")
            except OSError as e:
                logger.warning("Failed to ungrab: %s", e)
        else:
            try:
                fcntl.ioctl(self._fd, EVIOCGRAB, 1)
                self._grabbed = True
                self._gamepad_active = True
                logger.info("Device grabbed — gamepad mode active")
            except OSError as e:
                logger.warning("Failed to grab: %s", e)
        return self._gamepad_active

    def _grab_evdev(self) -> None:
        """Grab ALL controller evdev devices to prevent Steam from reading input.

        Steam Deck exposes multiple evdev devices for the same controller:
        - Valve Software Steam Controller (x2)
        - Microsoft X-Box 360 pad 0
        All must be grabbed to fully block Steam.
        """
        if self._evdev_grab_fds:
            return  # already grabbed
        grab_patterns = [VALVE_CONTROLLER_NAME] + DECK_CONTROLLER_NAMES
        for path in sorted(glob.glob("/dev/input/event*")):
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            name = _get_device_name(fd)
            matched = any(p.lower() in name.lower() for p in grab_patterns)
            if not matched:
                os.close(fd)
                continue
            try:
                fcntl.ioctl(fd, EVIOCGRAB, 1)
                self._evdev_grab_fds.append((fd, path))
                logger.info("Grabbed evdev %s (%s) — Steam input blocked", path, name)
            except OSError as e:
                os.close(fd)
                logger.warning("Failed to grab evdev %s (%s): %s", path, name, e)
        if not self._evdev_grab_fds:
            logger.warning("No evdev devices found to grab")

    def _ungrab_evdev(self) -> None:
        """Release all evdev grabs so Steam can read controller input again."""
        if not self._evdev_grab_fds:
            return
        for fd, path in self._evdev_grab_fds:
            try:
                fcntl.ioctl(fd, EVIOCGRAB, 0)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass
            logger.info("Released evdev grab on %s", path)
        self._evdev_grab_fds = []
        logger.info("All evdev grabs released — Steam input restored")

    # ------------------------------------------------------------------
    # HID driver rebind — block/unblock Steam from hidraw access
    # ------------------------------------------------------------------

    def _get_hid_device_id(self) -> str:
        """Get the HID bus device ID for the current hidraw (e.g. '0003:28DE:1205.0005')."""
        if not self._dev_path:
            return ""
        devname = os.path.basename(self._dev_path)  # e.g. "hidraw4"
        sysfs_device = f"/sys/class/hidraw/{devname}/device"
        try:
            real = os.path.realpath(sysfs_device)
            return os.path.basename(real)
        except OSError:
            return ""

    def _block_steam_input(self) -> bool:
        """Block Steam from accessing the controller by rebinding HID with restricted permissions.

        1. Write a udev rule that sets root-only permissions on Valve hidraw devices
        2. Reload udev rules
        3. Unbind the HID device from hid-steam (destroys current hidraw)
        4. Rebind to hid-steam (new hidraw created with restricted permissions)
        5. Reopen the new hidraw device

        Returns True if successful.
        """
        if self._steam_blocked:
            return True

        hid_id = self._get_hid_device_id()
        if not hid_id:
            logger.error("Cannot block Steam: no HID device ID found")
            return False

        logger.info("Blocking Steam input — HID device %s", hid_id)

        try:
            # Step 1: Write udev rule
            os.makedirs(os.path.dirname(_UDEV_RULE_PATH), exist_ok=True)
            with open(_UDEV_RULE_PATH, "w") as f:
                f.write(_UDEV_RULE_CONTENT)

            # Step 2: Reload udev rules
            subprocess.run(
                ["udevadm", "control", "--reload-rules"],
                check=True,
                timeout=5,
                env=_system_env(),
            )

            # Step 3: Close our fd (reader thread will get ENODEV or we close first)
            old_fd = self._fd
            self._fd = None
            if old_fd is not None:
                try:
                    os.close(old_fd)
                except OSError:
                    pass

            # Step 4: Unbind from hid-steam
            with open(_HID_STEAM_UNBIND, "w") as f:
                f.write(hid_id)

            # Step 5: Rebind (udev creates new hidraw with root-only permissions)
            time.sleep(0.1)
            with open(_HID_STEAM_BIND, "w") as f:
                f.write(hid_id)
            time.sleep(0.5)  # Wait for udev to apply rule + create device

            # Step 6: Reopen the new hidraw device
            result = self._find_hidraw_device()
            if result is None:
                logger.error("Failed to find new hidraw after rebind")
                self._unblock_steam_input()
                return False

            self._fd, self._dev_path = result
            self._hid_device_id = self._get_hid_device_id()
            self._steam_blocked = True
            logger.info(
                "Steam blocked — new hidraw %s (HID %s)",
                self._dev_path,
                self._hid_device_id,
            )
            return True

        except Exception as e:
            logger.error("Failed to block Steam input: %s", e)
            # Try to recover
            self._cleanup_udev_rule()
            return False

    def _unblock_steam_input(self) -> bool:
        """Restore Steam's access to the controller by rebinding HID with normal permissions.

        Returns True if successful.
        """
        if not self._steam_blocked:
            return True

        hid_id = self._get_hid_device_id()
        if not hid_id:
            # Try with stored ID
            hid_id = self._hid_device_id
        if not hid_id:
            logger.error("Cannot unblock Steam: no HID device ID")
            self._cleanup_udev_rule()
            return False

        logger.info("Unblocking Steam input — HID device %s", hid_id)

        try:
            # Step 1: Remove udev rule
            self._cleanup_udev_rule()

            # Step 2: Close our fd
            old_fd = self._fd
            self._fd = None
            if old_fd is not None:
                try:
                    os.close(old_fd)
                except OSError:
                    pass

            # Step 3: Unbind
            with open(_HID_STEAM_UNBIND, "w") as f:
                f.write(hid_id)

            # Step 4: Rebind (normal permissions — Steam will detect new device)
            time.sleep(0.1)
            with open(_HID_STEAM_BIND, "w") as f:
                f.write(hid_id)
            time.sleep(0.5)

            # Step 5: Reopen new hidraw
            result = self._find_hidraw_device()
            if result is None:
                logger.error("Failed to find new hidraw after unblock rebind")
                return False

            self._fd, self._dev_path = result
            self._hid_device_id = self._get_hid_device_id()
            self._steam_blocked = False
            logger.info(
                "Steam unblocked — new hidraw %s (HID %s)",
                self._dev_path,
                self._hid_device_id,
            )
            return True

        except Exception as e:
            logger.error("Failed to unblock Steam input: %s", e)
            return False

    @staticmethod
    def _cleanup_udev_rule() -> None:
        """Remove the temporary udev rule and reload."""
        try:
            os.unlink(_UDEV_RULE_PATH)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning("Failed to remove udev rule: %s", e)
        try:
            subprocess.run(
                ["udevadm", "control", "--reload-rules"],
                check=False,
                timeout=5,
                env=_system_env(),
            )
        except Exception:
            pass

    @property
    def gamepad_active(self) -> bool:
        """Whether gamepad mode is active (input forwarded to BT host)."""
        return self._gamepad_active

    @property
    def is_running(self) -> bool:
        """Whether the input reader is actively reading events."""
        return self._running

    @property
    def current_state(self) -> InputState:
        """Current gamepad state snapshot."""
        return self._state.copy()

    def _signal_reader_restart(self) -> None:
        """Signal the read loop to restart with the current (new) fd.

        Called after _block_steam_input / _unblock_steam_input swaps the fd.
        The old reader thread will die from ENODEV; the read loop restarts it.
        """
        self._device_swapped = True

    # ------------------------------------------------------------------
    # Read loop (threaded I/O → asyncio queue)
    # ------------------------------------------------------------------

    async def _read_loop(self) -> None:
        """Read loop using a background thread for blocking reads.

        Supports device swaps: when toggle_grab() rebinds the HID device,
        the old reader thread dies and this loop restarts it with the new fd.
        """
        if self._fd is None:
            return

        self._device_swapped = False
        loop = asyncio.get_event_loop()
        use_hidraw = self._use_hidraw
        read_size = VALVE_REPORT_SIZE if use_hidraw else INPUT_EVENT_SIZE * 64
        report_count = 0

        while self._running:
            fd = self._fd
            if fd is None:
                await asyncio.sleep(0.1)
                continue

            queue: asyncio.Queue[bytes] = asyncio.Queue()
            stop_event = threading.Event()
            self._device_swapped = False

            def _put_report(data: bytes) -> None:
                """Drop stale reports then enqueue newest. Runs in event loop."""
                while not queue.empty():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                queue.put_nowait(data)

            def _reader_thread(
                fd_local: int = fd,
                stop_local: threading.Event = stop_event,
                queue_local: asyncio.Queue[bytes] = queue,
            ) -> None:
                while not stop_local.is_set():
                    # Use select() for low-latency blocking wait; timeout lets us
                    # check stop_event periodically without busy-spinning.
                    ready, _, _ = select.select([fd_local], [], [], 0.05)
                    if not ready:
                        continue
                    try:
                        data = os.read(fd_local, read_size)
                        if data:
                            loop.call_soon_threadsafe(_put_report, data)
                    except BlockingIOError:
                        pass  # shouldn't happen with blocking fd, but handle gracefully
                    except OSError:
                        loop.call_soon_threadsafe(_put_report, b"")
                        break

            thread = threading.Thread(target=_reader_thread, daemon=True, name="input-reader")
            thread.start()
            logger.info(
                "Read loop started (threaded), fd=%s, mode=%s",
                fd,
                "hidraw" if use_hidraw else "evdev",
            )

            try:
                if use_hidraw:
                    while self._running:
                        data = await queue.get()
                        if not data:
                            break  # fd died — check for device swap
                        if len(data) == VALVE_REPORT_SIZE:
                            report_count += 1
                            if report_count <= 3 or report_count % 1000 == 0:
                                logger.info("hidraw #%d: %s", report_count, data[:16].hex())
                            self._process_hidraw_report(data)
                else:
                    buf = b""
                    while self._running:
                        data = await queue.get()
                        if not data:
                            break
                        buf += data
                        while len(buf) >= INPUT_EVENT_SIZE:
                            raw = buf[:INPUT_EVENT_SIZE]
                            buf = buf[INPUT_EVENT_SIZE:]
                            _sec, _usec, ev_type, ev_code, ev_value = struct.unpack(
                                INPUT_EVENT_FORMAT, raw
                            )
                            report_count += 1
                            if report_count <= 5 or report_count % 1000 == 0:
                                logger.info(
                                    "evdev #%d: type=%d code=0x%x val=%d",
                                    report_count,
                                    ev_type,
                                    ev_code,
                                    ev_value,
                                )
                            self._process_event(ev_type, ev_code, ev_value)
            except asyncio.CancelledError:
                stop_event.set()
                thread.join(timeout=1.0)
                raise
            except Exception as e:
                logger.error("Unexpected error in read loop: %s", e)
            finally:
                stop_event.set()
                thread.join(timeout=1.0)

            # If device was swapped (toggle_grab), restart with new fd
            if self._device_swapped and self._running:
                logger.info("Device swapped — restarting reader with new fd %s", self._fd)
                self._device_swapped = False
            else:
                break  # Normal exit or fatal error

    # ------------------------------------------------------------------
    # hidraw report processing (Valve Steam Deck format)
    # ------------------------------------------------------------------

    def _process_hidraw_report(self, data: bytes) -> None:
        """Process a raw 64-byte Valve Steam Deck HID report."""
        # Validate header
        version = struct.unpack_from("<H", data, 0)[0]
        report_type = data[2]
        if version != VALVE_REPORT_VERSION or report_type != VALVE_DECK_STATE_TYPE:
            return

        # Parse SteamDeckStatePacket_t at offset 4
        (
            _pkt_num,
            btns_l,
            btns_h,
            lpad_x,
            lpad_y,
            rpad_x,
            rpad_y,
            accel_x,
            accel_y,
            accel_z,
            gyro_x,
            gyro_y,
            gyro_z,
            gyro_qw,
            gyro_qx,
            gyro_qy,
            gyro_qz,
            trig_l,
            trig_r,
            lstick_x,
            lstick_y,
            rstick_x,
            rstick_y,
            pressure_l,
            pressure_r,
        ) = struct.unpack_from(_DECK_STATE_FMT, data, 4)

        # --- Change detection on key fields to avoid 250 reports/s when idle ---
        # NOTE: moved below after deadzone/processing; raw values jitter ±2 LSB

        # --- Map buttons ---
        buttons = 0
        for valve_bit, our_bit in _VALVE_BTNL_MAP:
            if btns_l & valve_bit:
                buttons |= 1 << our_bit
        for valve_bit, our_bit in _VALVE_BTNH_MAP:
            if btns_h & valve_bit:
                buttons |= 1 << our_bit

        # --- D-pad from button bits ---
        up = bool(btns_l & _VBL_DPAD_UP)
        down = bool(btns_l & _VBL_DPAD_DOWN)
        left = bool(btns_l & _VBL_DPAD_LEFT)
        right = bool(btns_l & _VBL_DPAD_RIGHT)
        if up and not down:
            dpad = 1 if right else (7 if left else 0)
        elif down and not up:
            dpad = 3 if right else (5 if left else 4)
        elif right:
            dpad = 2
        elif left:
            dpad = 6
        else:
            dpad = DPAD_NEUTRAL

        # --- Triggers: uint16 (0-32767) → uint8 (0-255) ---
        l2 = min(255, trig_l >> 7)
        r2 = min(255, trig_r >> 7)

        # --- Sticks: int16, apply deadzone, negate Y (hardware up = +Y) ---
        left_x = _apply_deadzone(lstick_x, self._deadzone, STICK_MAX)
        left_y = _apply_deadzone(-lstick_y, self._deadzone, STICK_MAX)
        right_x = _apply_deadzone(rstick_x, self._deadzone, STICK_MAX)
        right_y = _apply_deadzone(-rstick_y, self._deadzone, STICK_MAX)

        # --- Update state ---
        self._state.buttons = buttons
        self._state.left_x = left_x
        self._state.left_y = left_y
        self._state.right_x = right_x
        self._state.right_y = right_y
        self._state.l2 = l2
        self._state.r2 = r2
        self._state.dpad = dpad
        self._state.trackpad_left_x = lpad_x
        self._state.trackpad_left_y = lpad_y
        self._state.trackpad_right_x = rpad_x
        self._state.trackpad_right_y = rpad_y
        self._state.trackpad_left_touch = bool(btns_l & _VBL_LPAD_TOUCH)
        self._state.trackpad_right_touch = bool(btns_l & _VBL_RPAD_TOUCH)
        self._state.trackpad_left_click = bool(btns_l & _VBL_LPAD_CLICK)
        self._state.trackpad_right_click = bool(btns_l & _VBL_RPAD_CLICK)

        # --- Toggle combo: L4+R4 ---
        l4_pressed = bool(btns_h & _VBH_L4)
        r4_pressed = bool(btns_h & _VBH_R4)
        if l4_pressed and r4_pressed:
            if not self._combo_active and self._toggle_callback is not None:
                self._combo_active = True
                self._toggle_callback()
            return  # Don't forward combo press
        else:
            self._combo_active = False

        # --- Change detection (post-deadzone to ignore ADC jitter) ---
        key_state = (
            buttons,
            left_x,
            left_y,
            right_x,
            right_y,
            l2,
            r2,
            dpad,
            self._state.trackpad_right_x,
            self._state.trackpad_right_y,
            self._state.trackpad_left_x,
            self._state.trackpad_left_y,
            self._state.trackpad_right_touch,
            self._state.trackpad_left_touch,
            self._state.trackpad_right_click,
            self._state.trackpad_left_click,
        )
        if key_state == self._prev_key_state:
            return
        self._prev_key_state = key_state

        # --- Forward to callback ---
        if self._gamepad_active and self._callback is not None:
            self._callback(self._state.copy())

    # ------------------------------------------------------------------
    # evdev event processing (fallback)
    # ------------------------------------------------------------------

    def _process_event(self, ev_type: int, code: int, value: int) -> None:
        """Process a single evdev input event."""
        changed = False

        if ev_type == EV_KEY:
            if code in _BUTTON_MAP:
                bit = _BUTTON_MAP[code]
                if value:
                    self._state.buttons |= 1 << bit
                else:
                    self._state.buttons &= ~(1 << bit)
                changed = True
        elif ev_type == EV_ABS:
            if code == ABS_X:
                self._state.left_x = _apply_deadzone(value, self._deadzone, STICK_MAX)
                changed = True
            elif code == ABS_Y:
                self._state.left_y = _apply_deadzone(value, self._deadzone, STICK_MAX)
                changed = True
            elif code == ABS_RX:
                self._state.right_x = _apply_deadzone(value, self._deadzone, STICK_MAX)
                changed = True
            elif code == ABS_RY:
                self._state.right_y = _apply_deadzone(value, self._deadzone, STICK_MAX)
                changed = True
            elif code == ABS_Z:
                self._state.l2 = max(0, min(TRIGGER_MAX, value))
                changed = True
            elif code == ABS_RZ:
                self._state.r2 = max(0, min(TRIGGER_MAX, value))
                changed = True
            elif code == ABS_HAT0X:
                self._hat_x = value
                self._state.dpad = _DPAD_MAP.get((self._hat_x, self._hat_y), DPAD_NEUTRAL)
                changed = True
            elif code == ABS_HAT0Y:
                self._hat_y = value
                self._state.dpad = _DPAD_MAP.get((self._hat_x, self._hat_y), DPAD_NEUTRAL)
                changed = True

        if changed and self._callback is not None:
            if (
                ev_type == EV_KEY
                and value == 1
                and code in (BTN_TRIGGER_HAPPY1, BTN_TRIGGER_HAPPY3)
            ):
                l4 = bool(self._state.buttons & (1 << _BUTTON_MAP[BTN_TRIGGER_HAPPY1]))
                r4 = bool(self._state.buttons & (1 << _BUTTON_MAP[BTN_TRIGGER_HAPPY3]))
                if l4 and r4 and self._toggle_callback is not None:
                    self._toggle_callback()
                    return
            if self._gamepad_active:
                self._callback(self._state.copy())
