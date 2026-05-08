"""Tests for backend.trackpad_mouse — trackpad-to-mouse delta conversion."""

from __future__ import annotations

from backend.trackpad_mouse import TrackpadMouse


class TestTrackpadMouseDefaults:
    def test_default_sensitivity(self):
        t = TrackpadMouse()
        assert t.sensitivity == 1.0
        assert t.scroll_sensitivity == 1.0

    def test_custom_sensitivity(self):
        t = TrackpadMouse(sensitivity=2.0, scroll_sensitivity=0.5)
        assert t.sensitivity == 2.0
        assert t.scroll_sensitivity == 0.5


class TestUpdateRight:
    def test_not_touching_returns_zero(self):
        t = TrackpadMouse()
        assert t.update_right(1000, 1000, False) == (0, 0)

    def test_first_touch_returns_zero(self):
        t = TrackpadMouse()
        assert t.update_right(1000, 1000, True) == (0, 0)

    def test_movement_after_first_touch(self):
        t = TrackpadMouse()
        t.update_right(1000, 1000, True)  # first touch
        dx, dy = t.update_right(1256, 1000, True)  # move right by 256
        assert dx == 1  # 256 * 1.0 / 256 = 1
        assert dy == 0

    def test_negative_movement(self):
        t = TrackpadMouse()
        t.update_right(1000, 1000, True)
        dx, dy = t.update_right(744, 1000, True)  # move left by 256
        assert dx == -1
        assert dy == 0

    def test_large_movement_clamped(self):
        t = TrackpadMouse(sensitivity=10.0)
        t.update_right(0, 0, True)
        dx, dy = t.update_right(32767, 32767, True)  # max movement
        assert dx == 127
        assert dy == 127

    def test_large_negative_clamped(self):
        t = TrackpadMouse(sensitivity=10.0)
        t.update_right(32767, 32767, True)
        dx, dy = t.update_right(0, 0, True)
        assert dx == -127
        assert dy == -127

    def test_release_resets_tracking(self):
        t = TrackpadMouse()
        t.update_right(1000, 1000, True)
        t.update_right(1256, 1256, True)
        t.update_right(0, 0, False)  # release
        # Next touch should be treated as first touch
        assert t.update_right(5000, 5000, True) == (0, 0)

    def test_sensitivity_scaling(self):
        t = TrackpadMouse(sensitivity=2.0)
        t.update_right(1000, 1000, True)
        dx, dy = t.update_right(1256, 1000, True)  # 256 delta
        assert dx == 2  # 256 * 2.0 / 256 = 2

    def test_zero_sensitivity(self):
        t = TrackpadMouse(sensitivity=0.0)
        t.update_right(1000, 1000, True)
        dx, dy = t.update_right(2000, 2000, True)
        assert dx == 0
        assert dy == 0


class TestUpdateLeft:
    def test_not_touching_returns_zero(self):
        t = TrackpadMouse()
        assert t.update_left(1000, False) == 0

    def test_first_touch_returns_zero(self):
        t = TrackpadMouse()
        assert t.update_left(1000, True) == 0

    def test_scroll_up(self):
        t = TrackpadMouse()
        t.update_left(1000, True)
        # Moving finger up = decreasing Y → positive wheel (scroll up)
        wheel = t.update_left(488, True)  # delta = -512
        assert wheel == 1  # int(-(-512) * 1.0 / 512) = 1

    def test_scroll_down(self):
        t = TrackpadMouse()
        t.update_left(1000, True)
        wheel = t.update_left(1512, True)  # delta = +512
        assert wheel == -1  # int(-(512) * 1.0 / 512) = -1

    def test_scroll_clamped(self):
        t = TrackpadMouse(scroll_sensitivity=10.0)
        t.update_left(0, True)
        wheel = t.update_left(32767, True)
        assert wheel == -127

    def test_release_resets(self):
        t = TrackpadMouse()
        t.update_left(1000, True)
        t.update_left(2000, True)
        t.update_left(0, False)  # release
        assert t.update_left(5000, True) == 0  # first touch again


class TestReset:
    def test_reset_clears_all_state(self):
        t = TrackpadMouse()
        t.update_right(1000, 1000, True)
        t.update_left(500, True)
        t.reset()
        # After reset, next touch is treated as first touch
        assert t.update_right(2000, 2000, True) == (0, 0)
        assert t.update_left(1000, True) == 0
