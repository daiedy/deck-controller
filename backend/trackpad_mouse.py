"""Trackpad to mouse delta conversion for Steam Deck trackpads."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Acceleration curve parameters
_ACCEL_THRESHOLD = 3.0  # Below this speed: 1:1 (precise aiming)
_ACCEL_MULTIPLIER = 1.8  # Speed boost above threshold
_ACCEL_CAP = 6.0  # Maximum multiplier cap

# Base scaling: trackpad units → mouse units
# Trackpad range ~±16384, at 250Hz a fast swipe produces ~2000 units/frame.
# We want slow movement (< 200 units) to map precisely and fast movement
# (> 500 units) to cover large screen distances.
_BASE_SCALE = 1.0 / 128  # Increased from 1/256 — more responsive base


def _apply_acceleration(raw: float) -> float:
    """Apply mouse-style acceleration curve to a raw delta.

    Below threshold: linear 1:1 mapping (precision).
    Above threshold: power curve for faster large movements.
    """
    magnitude = abs(raw)
    if magnitude < _ACCEL_THRESHOLD:
        return raw
    # Smooth acceleration above threshold
    accel = 1.0 + (_ACCEL_MULTIPLIER - 1.0) * math.log1p(magnitude - _ACCEL_THRESHOLD)
    accel = min(accel, _ACCEL_CAP)
    return raw * accel


@dataclass
class TrackpadMouse:
    """Converts absolute trackpad positions to relative mouse deltas.

    Steam Deck trackpads report absolute positions as signed int16 with Y
    increasing upward (hardware up = +Y, same convention as the sticks).
    This class tracks previous positions and calculates deltas.

    Uses a mouse-style acceleration curve: slow movements are precise,
    fast movements cover large distances.
    """

    sensitivity: float = 1.0
    scroll_sensitivity: float = 1.0

    _prev_right_x: int = field(default=-1, repr=False)
    _prev_right_y: int = field(default=-1, repr=False)
    _prev_left_y: int = field(default=-1, repr=False)
    _right_touching: bool = field(default=False, repr=False)
    _left_touching: bool = field(default=False, repr=False)
    # Sub-pixel accumulators to prevent small movements being eaten by int truncation
    _accum_x: float = field(default=0.0, repr=False)
    _accum_y: float = field(default=0.0, repr=False)
    _accum_scroll: float = field(default=0.0, repr=False)

    def update_right(self, x: int, y: int, touching: bool) -> tuple[int, int]:
        """Update right trackpad position, return (dx, dy) mouse delta.

        Args:
            x: Absolute X position (signed int16, increases to the right).
            y: Absolute Y position (signed int16, increases upward).
            touching: Whether finger is touching the pad.

        Returns:
            Tuple of (dx, dy) relative movement, clamped to -127..127.
            Positive dx = right, positive dy = down (standard HID mouse axes).
        """
        if not touching:
            self._prev_right_x = -1
            self._prev_right_y = -1
            self._right_touching = False
            self._accum_x = 0.0
            self._accum_y = 0.0
            return (0, 0)

        if not self._right_touching or self._prev_right_x == -1:
            # First touch — record position, no movement
            self._prev_right_x = x
            self._prev_right_y = y
            self._right_touching = True
            return (0, 0)

        # Calculate raw delta
        raw_dx = x - self._prev_right_x
        raw_dy = y - self._prev_right_y
        self._prev_right_x = x
        self._prev_right_y = y

        # Scale to mouse units and apply acceleration
        # Y is negated: hardware Y increases upward, HID mouse Y increases downward.
        scaled_dx = raw_dx * self.sensitivity * _BASE_SCALE
        scaled_dy = -raw_dy * self.sensitivity * _BASE_SCALE

        # Apply acceleration curve (makes slow movements precise, fast movements big)
        accel_dx = _apply_acceleration(scaled_dx)
        accel_dy = _apply_acceleration(scaled_dy)

        # Accumulate sub-pixel fractions
        self._accum_x += accel_dx
        self._accum_y += accel_dy

        dx = int(self._accum_x)
        dy = int(self._accum_y)
        self._accum_x -= dx
        self._accum_y -= dy

        return (max(-127, min(127, dx)), max(-127, min(127, dy)))

    def update_left(self, y: int, touching: bool) -> int:
        """Update left trackpad Y position, return scroll wheel delta.

        Args:
            y: Absolute Y position (signed int16, increases upward).
            touching: Whether finger is touching the pad.

        Returns:
            Scroll wheel delta, clamped to -127..127 (positive = scroll up).
        """
        if not touching:
            self._prev_left_y = -1
            self._left_touching = False
            self._accum_scroll = 0.0
            return 0

        if not self._left_touching or self._prev_left_y == -1:
            self._prev_left_y = y
            self._left_touching = True
            return 0

        raw_dy = y - self._prev_left_y
        self._prev_left_y = y

        # Moving finger up (increasing Y) = scroll up (positive wheel).
        self._accum_scroll += raw_dy * self.scroll_sensitivity / 512
        wheel = int(self._accum_scroll)
        self._accum_scroll -= wheel
        return max(-127, min(127, wheel))

    def reset(self) -> None:
        """Reset all tracking state."""
        self._prev_right_x = -1
        self._prev_right_y = -1
        self._prev_left_y = -1
        self._right_touching = False
        self._left_touching = False
        self._accum_x = 0.0
        self._accum_y = 0.0
        self._accum_scroll = 0.0
