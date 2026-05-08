"""Tests for backend.hid_descriptor — report packing and constants."""

from __future__ import annotations

import struct

from backend.hid_descriptor import (
    BTN_A,
    BTN_B,
    BTN_HOME,
    BTN_L1,
    BTN_L4,
    BTN_L5,
    BTN_R4,
    BTN_R5,
    BTN_SELECT,
    BTN_START,
    BTN_X,
    BTN_Y,
    COMPOSITE_REPORT_DESCRIPTOR,
    DPAD_DOWN,
    DPAD_LEFT,
    DPAD_NEUTRAL,
    DPAD_RIGHT,
    DPAD_UP,
    DPAD_UP_LEFT,
    GAMEPAD_REPORT_DESCRIPTOR,
    MOUSE_REPORT_DESCRIPTOR,
    MOTION_REPORT_DESCRIPTOR,
    REPORT_SIZE,
    pack_motion_report,
    pack_mouse_report,
    pack_report,
)


# ---- Descriptor sanity checks ----


class TestDescriptors:
    def test_gamepad_descriptor_is_bytes(self):
        assert isinstance(GAMEPAD_REPORT_DESCRIPTOR, bytes)
        assert len(GAMEPAD_REPORT_DESCRIPTOR) > 0

    def test_mouse_descriptor_is_bytes(self):
        assert isinstance(MOUSE_REPORT_DESCRIPTOR, bytes)

    def test_motion_descriptor_is_bytes(self):
        assert isinstance(MOTION_REPORT_DESCRIPTOR, bytes)

    def test_composite_descriptor_is_concatenation(self):
        expected = GAMEPAD_REPORT_DESCRIPTOR + MOUSE_REPORT_DESCRIPTOR + MOTION_REPORT_DESCRIPTOR
        assert COMPOSITE_REPORT_DESCRIPTOR == expected

    def test_report_size_is_15(self):
        assert REPORT_SIZE == 15


# ---- Constants ----


class TestConstants:
    def test_dpad_neutral(self):
        assert DPAD_NEUTRAL == 0x0F

    def test_dpad_directions(self):
        assert DPAD_UP == 0
        assert DPAD_RIGHT == 2
        assert DPAD_DOWN == 4
        assert DPAD_LEFT == 6

    def test_button_bit_positions(self):
        assert BTN_A == 0
        assert BTN_B == 1
        assert BTN_X == 2
        assert BTN_Y == 3
        assert BTN_L1 == 4
        assert BTN_SELECT == 8
        assert BTN_START == 9
        assert BTN_HOME == 12
        assert BTN_L4 == 13
        assert BTN_L5 == 14
        assert BTN_R4 == 15
        assert BTN_R5 == 16


# ---- pack_report ----


class TestPackReport:
    def test_report_id_is_0x01(self):
        data = pack_report(0, 0, 0, 0, 0, 0, 0, DPAD_NEUTRAL)
        assert data[0] == 0x01

    def test_report_length(self):
        data = pack_report(0, 0, 0, 0, 0, 0, 0, DPAD_NEUTRAL)
        assert len(data) == REPORT_SIZE

    def test_all_zeros(self):
        data = pack_report(0, 0, 0, 0, 0, 0, 0, DPAD_NEUTRAL)
        # Report ID + 3 zero button bytes + axes
        assert data[0] == 0x01
        assert data[1:4] == b"\x00\x00\x00"

    def test_button_a_pressed(self):
        buttons = 1 << BTN_A  # bit 0
        data = pack_report(buttons, 0, 0, 0, 0, 0, 0, DPAD_NEUTRAL)
        assert data[1] & 0x01 == 1  # bit 0 of first button byte

    def test_button_y_pressed(self):
        buttons = 1 << BTN_Y  # bit 3
        data = pack_report(buttons, 0, 0, 0, 0, 0, 0, DPAD_NEUTRAL)
        assert data[1] & 0x08 == 0x08

    def test_multiple_buttons(self):
        buttons = (1 << BTN_A) | (1 << BTN_B) | (1 << BTN_X)
        data = pack_report(buttons, 0, 0, 0, 0, 0, 0, DPAD_NEUTRAL)
        assert data[1] & 0x07 == 0x07

    def test_buttons_masked_to_20_bits(self):
        buttons = 0xFFFFFFFF  # all 32 bits set
        data = pack_report(buttons, 0, 0, 0, 0, 0, 0, DPAD_NEUTRAL)
        btn_value = int.from_bytes(data[1:4], "little")
        assert btn_value == 0xFFFFF  # only 20 bits

    def test_axes_full_positive(self):
        data = pack_report(0, 32767, 32767, 32767, 32767, 255, 255, DPAD_NEUTRAL)
        lx, ly, rx, ry, l2, r2, dpad = struct.unpack_from("<hhhhBBB", data, 4)
        assert lx == 32767
        assert ly == 32767
        assert rx == 32767
        assert ry == 32767
        assert l2 == 255
        assert r2 == 255

    def test_axes_full_negative(self):
        data = pack_report(0, -32768, -32768, -32768, -32768, 0, 0, DPAD_NEUTRAL)
        lx, ly, rx, ry, _, _, _ = struct.unpack_from("<hhhhBBB", data, 4)
        assert lx == -32768
        assert ly == -32768

    def test_clamping_axes(self):
        data = pack_report(0, 99999, -99999, 0, 0, 999, -10, DPAD_NEUTRAL)
        lx, ly, _, _, l2, r2, _ = struct.unpack_from("<hhhhBBB", data, 4)
        assert lx == 32767
        assert ly == -32768
        assert l2 == 255
        assert r2 == 0

    def test_dpad_up(self):
        data = pack_report(0, 0, 0, 0, 0, 0, 0, DPAD_UP)
        _, _, _, _, _, _, dpad = struct.unpack_from("<hhhhBBB", data, 4)
        assert dpad == 0

    def test_dpad_neutral(self):
        data = pack_report(0, 0, 0, 0, 0, 0, 0, DPAD_NEUTRAL)
        _, _, _, _, _, _, dpad = struct.unpack_from("<hhhhBBB", data, 4)
        assert dpad == 0x0F

    def test_dpad_masked_to_4_bits(self):
        data = pack_report(0, 0, 0, 0, 0, 0, 0, 0xFF)
        _, _, _, _, _, _, dpad = struct.unpack_from("<hhhhBBB", data, 4)
        assert dpad == 0x0F


# ---- pack_mouse_report ----


class TestPackMouseReport:
    def test_report_id_is_0x02(self):
        data = pack_mouse_report(0, 0, 0, 0)
        assert data[0] == 0x02

    def test_length(self):
        data = pack_mouse_report(0, 0, 0, 0)
        assert len(data) == 5

    def test_all_zeros(self):
        data = pack_mouse_report(0, 0, 0, 0)
        assert data == b"\x02\x00\x00\x00\x00"

    def test_left_button(self):
        data = pack_mouse_report(0x01, 0, 0, 0)
        assert data[1] == 0x01

    def test_buttons_masked_to_3_bits(self):
        data = pack_mouse_report(0xFF, 0, 0, 0)
        assert data[1] == 0x07

    def test_movement(self):
        data = pack_mouse_report(0, 50, -30, 5)
        _, _, dx, dy, wheel = struct.unpack("<BBbbb", data)
        assert dx == 50
        assert dy == -30
        assert wheel == 5

    def test_clamping(self):
        data = pack_mouse_report(0, 200, -200, 200)
        _, _, dx, dy, wheel = struct.unpack("<BBbbb", data)
        assert dx == 127
        assert dy == -127
        assert wheel == 127


# ---- pack_motion_report ----


class TestPackMotionReport:
    def test_report_id_is_0x03(self):
        data = pack_motion_report(0, 0, 0, 0, 0, 0)
        assert data[0] == 0x03

    def test_length(self):
        data = pack_motion_report(0, 0, 0, 0, 0, 0)
        assert len(data) == 13  # 1 + 6*2

    def test_all_zeros(self):
        data = pack_motion_report(0, 0, 0, 0, 0, 0)
        _, gx, gy, gz, ax, ay, az = struct.unpack("<Bhhhhhh", data)
        assert (gx, gy, gz, ax, ay, az) == (0, 0, 0, 0, 0, 0)

    def test_values(self):
        data = pack_motion_report(100, -200, 300, 1000, -1000, 16000)
        _, gx, gy, gz, ax, ay, az = struct.unpack("<Bhhhhhh", data)
        assert gx == 100
        assert gy == -200
        assert gz == 300
        assert ax == 1000
        assert ay == -1000
        assert az == 16000

    def test_clamping(self):
        data = pack_motion_report(99999, -99999, 0, 0, 0, 0)
        _, gx, gy, *_ = struct.unpack("<Bhhhhhh", data)
        assert gx == 32767
        assert gy == -32768
