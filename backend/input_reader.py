"""Evdev input reader for Steam Deck built-in gamepad."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

try:
    import evdev  # type: ignore[import-untyped]
    from evdev import InputDevice, categorize, ecodes  # type: ignore[import-untyped]
except ImportError:
    evdev = None  # type: ignore[assignment]

from .hid_descriptor import DPAD_NEUTRAL

logger = logging.getLogger("deck-controller.input_reader")

# Steam Deck controller device name patterns
DECK_CONTROLLER_NAMES: list[str] = [
    "Microsoft X-Box 360 pad",
    "Steam Deck",
    "Valve Software Steam Controller",
]

# Axis ranges for normalization
STICK_MIN: int = -32768
STICK_MAX: int = 32767
TRIGGER_MAX: int = 255


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
        )


# Mapping from evdev button codes to button bit positions
_BUTTON_MAP: dict[int, int] = {}
if evdev is not None:
    _BUTTON_MAP = {
        ecodes.BTN_A: 0,
        ecodes.BTN_B: 1,
        ecodes.BTN_X: 2,
        ecodes.BTN_Y: 3,
        ecodes.BTN_TL: 4,   # L1
        ecodes.BTN_TR: 5,   # R1
        ecodes.BTN_TL2: 6,  # L2 digital
        ecodes.BTN_TR2: 7,  # R2 digital
        ecodes.BTN_SELECT: 8,
        ecodes.BTN_START: 9,
        ecodes.BTN_THUMBL: 10,  # L3
        ecodes.BTN_THUMBR: 11,  # R3
        ecodes.BTN_MODE: 12,    # Home
    }

# D-pad value mapping from (ABS_HAT0X, ABS_HAT0Y) to hat switch
_DPAD_MAP: dict[tuple[int, int], int] = {
    (0, 0): DPAD_NEUTRAL,
    (0, -1): 0,    # Up
    (1, -1): 1,    # Up-Right
    (1, 0): 2,     # Right
    (1, 1): 3,     # Down-Right
    (0, 1): 4,     # Down
    (-1, 1): 5,    # Down-Left
    (-1, 0): 6,    # Left
    (-1, -1): 7,   # Up-Left
}


def _apply_deadzone(value: int, deadzone: float, axis_max: int) -> int:
    """Apply deadzone to an axis value.

    Args:
        value: Raw axis value.
        deadzone: Deadzone threshold as a fraction (0.0 to 1.0).
        axis_max: Maximum absolute axis value.

    Returns:
        Processed axis value with deadzone applied.
    """
    threshold = int(axis_max * deadzone)
    if abs(value) < threshold:
        return 0
    return value


class InputReader:
    """Reads input from Steam Deck's built-in gamepad via evdev.

    Finds the controller device, optionally grabs it exclusively, and reads
    events asynchronously. Calls back on state changes with normalized data.
    """

    def __init__(self, deadzone: float = 0.05) -> None:
        self._device: Optional[InputDevice] = None
        self._running: bool = False
        self._task: Optional[asyncio.Task[None]] = None
        self._state: InputState = InputState()
        self._deadzone: float = deadzone
        self._callback: Optional[Callable[[InputState], None]] = None
        self._grabbed: bool = False
        self._hat_x: int = 0
        self._hat_y: int = 0

    @staticmethod
    def find_devices() -> list[dict[str, str]]:
        """Find available gamepad devices.

        Returns:
            List of dicts with 'path', 'name', and 'phys' for each device.
        """
        if evdev is None:
            logger.warning("evdev not available")
            return []

        devices: list[dict[str, str]] = []
        for path in evdev.list_devices():
            try:
                dev = InputDevice(path)
                for pattern in DECK_CONTROLLER_NAMES:
                    if pattern.lower() in dev.name.lower():
                        devices.append({
                            "path": dev.path,
                            "name": dev.name,
                            "phys": dev.phys or "",
                        })
                        break
                dev.close()
            except (OSError, PermissionError):
                continue
        return devices

    def _find_device(self) -> Optional[InputDevice]:
        """Find the first matching Steam Deck controller device."""
        if evdev is None:
            return None

        for path in evdev.list_devices():
            try:
                dev = InputDevice(path)
                for pattern in DECK_CONTROLLER_NAMES:
                    if pattern.lower() in dev.name.lower():
                        logger.info("Found controller: %s at %s", dev.name, dev.path)
                        return dev
                dev.close()
            except (OSError, PermissionError) as e:
                logger.debug("Cannot open %s: %s", path, e)
                continue
        return None

    async def start(self, callback: Callable[[InputState], None], grab: bool = True) -> bool:
        """Start reading input events.

        Args:
            callback: Called with updated InputState on each state change.
            grab: If True, exclusively grab the device (EVIOCGRAB).

        Returns:
            True if successfully started, False otherwise.
        """
        if self._running:
            logger.warning("Input reader already running")
            return False

        self._device = self._find_device()
        if self._device is None:
            logger.error("No controller device found")
            return False

        self._callback = callback

        if grab:
            try:
                self._device.grab()
                self._grabbed = True
                logger.info("Grabbed device exclusively")
            except OSError as e:
                logger.warning("Could not grab device: %s", e)
                self._grabbed = False

        self._running = True
        self._state = InputState()
        self._task = asyncio.create_task(self._read_loop())
        logger.info("Input reader started")
        return True

    async def stop(self) -> None:
        """Stop reading input events and release the device."""
        self._running = False

        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._device is not None:
            if self._grabbed:
                try:
                    self._device.ungrab()
                except OSError:
                    pass
                self._grabbed = False
            try:
                self._device.close()
            except OSError:
                pass
            self._device = None

        logger.info("Input reader stopped")

    async def _read_loop(self) -> None:
        """Main event reading loop."""
        if self._device is None:
            return

        try:
            async for event in self._device.async_read_loop():
                if not self._running:
                    break
                self._process_event(event)
        except asyncio.CancelledError:
            raise
        except OSError as e:
            logger.error("Device read error: %s", e)
            self._running = False
        except Exception as e:
            logger.error("Unexpected error in read loop: %s", e)
            self._running = False

    def _process_event(self, event: object) -> None:
        """Process a single evdev input event."""
        if evdev is None:
            return

        changed = False

        if event.type == ecodes.EV_KEY:  # type: ignore[union-attr]
            code = event.code  # type: ignore[union-attr]
            value = event.value  # type: ignore[union-attr]
            if code in _BUTTON_MAP:
                bit = _BUTTON_MAP[code]
                if value:
                    self._state.buttons |= (1 << bit)
                else:
                    self._state.buttons &= ~(1 << bit)
                changed = True

        elif event.type == ecodes.EV_ABS:  # type: ignore[union-attr]
            code = event.code  # type: ignore[union-attr]
            value = event.value  # type: ignore[union-attr]

            if code == ecodes.ABS_X:
                self._state.left_x = _apply_deadzone(value, self._deadzone, STICK_MAX)
                changed = True
            elif code == ecodes.ABS_Y:
                self._state.left_y = _apply_deadzone(value, self._deadzone, STICK_MAX)
                changed = True
            elif code == ecodes.ABS_RX:
                self._state.right_x = _apply_deadzone(value, self._deadzone, STICK_MAX)
                changed = True
            elif code == ecodes.ABS_RY:
                self._state.right_y = _apply_deadzone(value, self._deadzone, STICK_MAX)
                changed = True
            elif code == ecodes.ABS_Z:
                self._state.l2 = max(0, min(TRIGGER_MAX, value))
                changed = True
            elif code == ecodes.ABS_RZ:
                self._state.r2 = max(0, min(TRIGGER_MAX, value))
                changed = True
            elif code == ecodes.ABS_HAT0X:
                self._hat_x = value
                self._state.dpad = _DPAD_MAP.get(
                    (self._hat_x, self._hat_y), DPAD_NEUTRAL
                )
                changed = True
            elif code == ecodes.ABS_HAT0Y:
                self._hat_y = value
                self._state.dpad = _DPAD_MAP.get(
                    (self._hat_x, self._hat_y), DPAD_NEUTRAL
                )
                changed = True

        if changed and self._callback is not None:
            self._callback(self._state.copy())

    @property
    def is_running(self) -> bool:
        """Whether the input reader is actively reading events."""
        return self._running

    @property
    def current_state(self) -> InputState:
        """Current gamepad state snapshot."""
        return self._state.copy()
