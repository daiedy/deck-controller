"""Trackpad to mouse delta conversion for Steam Deck trackpads."""

from __future__ import annotations

from dataclasses import dataclass, field

# Base scaling: trackpad units → mouse units.
# Linear scale — no acceleration curve. Predictable 1:1 feel at all speeds.
# Steam Deck trackpad ≈32768 units across ~40mm surface, at 250Hz.
# 256 trackpad units = 1 mouse pixel. A moderate swipe (~50mm/s) produces
# ~160 units/frame → ~0.6 px/frame → ~156 px/sec (comfortable desktop speed).
_BASE_SCALE = 1.0 / 256


@dataclass
class TrackpadMouse:
    """Converts absolute trackpad positions to relative mouse deltas.

    Steam Deck trackpads report absolute positions as signed int16 with Y
    increasing upward (hardware up = +Y, same convention as the sticks).
    This class tracks previous positions and calculates deltas.

    Uses linear scaling (no acceleration) for predictable, consistent feel.
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

        # Scale to mouse units (linear, no acceleration)
        # Y is negated: hardware Y increases upward, HID mouse Y increases downward.
        scaled_dx = raw_dx * self.sensitivity * _BASE_SCALE
        scaled_dy = -raw_dy * self.sensitivity * _BASE_SCALE

        # Accumulate sub-pixel fractions
        self._accum_x += scaled_dx
        self._accum_y += scaled_dy

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
