"""Trackpad to mouse delta conversion for Steam Deck trackpads."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TrackpadMouse:
    """Converts absolute trackpad positions to relative mouse deltas.

    Steam Deck trackpads report absolute positions (0-32767).
    This class tracks previous positions and calculates deltas.
    """

    sensitivity: float = 1.0
    scroll_sensitivity: float = 1.0

    _prev_right_x: int = field(default=-1, repr=False)
    _prev_right_y: int = field(default=-1, repr=False)
    _prev_left_y: int = field(default=-1, repr=False)
    _right_touching: bool = field(default=False, repr=False)
    _left_touching: bool = field(default=False, repr=False)

    def update_right(self, x: int, y: int, touching: bool) -> tuple[int, int]:
        """Update right trackpad position, return (dx, dy) mouse delta.

        Args:
            x: Absolute X position (0-32767).
            y: Absolute Y position (0-32767).
            touching: Whether finger is touching the pad.

        Returns:
            Tuple of (dx, dy) relative movement, clamped to -127..127.
        """
        if not touching:
            self._prev_right_x = -1
            self._prev_right_y = -1
            self._right_touching = False
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

        # Scale: trackpad range 0-32767, mouse delta -127..127
        # Divide by 256 gives ~128 px of travel across full pad at sensitivity=1.0
        dx = int(raw_dx * self.sensitivity / 256)
        dy = int(raw_dy * self.sensitivity / 256)

        return (max(-127, min(127, dx)), max(-127, min(127, dy)))

    def update_left(self, y: int, touching: bool) -> int:
        """Update left trackpad Y position, return scroll wheel delta.

        Args:
            y: Absolute Y position (0-32767).
            touching: Whether finger is touching the pad.

        Returns:
            Scroll wheel delta, clamped to -127..127 (positive = scroll up).
        """
        if not touching:
            self._prev_left_y = -1
            self._left_touching = False
            return 0

        if not self._left_touching or self._prev_left_y == -1:
            self._prev_left_y = y
            self._left_touching = True
            return 0

        raw_dy = y - self._prev_left_y
        self._prev_left_y = y

        # Invert: moving finger up (decreasing Y) = scroll up (positive wheel)
        wheel = int(-raw_dy * self.scroll_sensitivity / 512)
        return max(-127, min(127, wheel))

    def reset(self) -> None:
        """Reset all tracking state."""
        self._prev_right_x = -1
        self._prev_right_y = -1
        self._prev_left_y = -1
        self._right_touching = False
        self._left_touching = False
