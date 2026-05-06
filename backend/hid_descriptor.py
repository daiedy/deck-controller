"""HID Report Descriptor and report packing for Xbox-compatible gamepad layout."""

from __future__ import annotations

import struct

# Xbox-compatible gamepad HID Report Descriptor
# Report ID: 0x01
# Layout:
#   - 16 buttons (2 bytes)
#   - Left stick X, Y + Right stick X, Y (4 x int16)
#   - L2, R2 triggers (2 x uint8)
#   - D-pad hat switch (4-bit) + 4-bit padding
GAMEPAD_REPORT_DESCRIPTOR: bytes = bytes([
    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x05,        # Usage (Gamepad)
    0xA1, 0x01,        # Collection (Application)
    0x85, 0x01,        #   Report ID (1)

    # 16 buttons
    0x05, 0x09,        #   Usage Page (Button)
    0x19, 0x01,        #   Usage Minimum (1)
    0x29, 0x10,        #   Usage Maximum (16)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x01,        #   Logical Maximum (1)
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x10,        #   Report Count (16)
    0x81, 0x02,        #   Input (Data, Var, Abs)

    # Left stick X, Y + Right stick X, Y — 16-bit signed
    0x05, 0x01,        #   Usage Page (Generic Desktop)
    0x09, 0x30,        #   Usage (X)
    0x09, 0x31,        #   Usage (Y)
    0x09, 0x32,        #   Usage (Z)
    0x09, 0x35,        #   Usage (Rz)
    0x16, 0x00, 0x80,  #   Logical Minimum (-32768)
    0x26, 0xFF, 0x7F,  #   Logical Maximum (32767)
    0x75, 0x10,        #   Report Size (16)
    0x95, 0x04,        #   Report Count (4)
    0x81, 0x02,        #   Input (Data, Var, Abs)

    # L2, R2 triggers — 8-bit unsigned
    0x05, 0x02,        #   Usage Page (Simulation Controls)
    0x09, 0xC5,        #   Usage (Brake — L2)
    0x09, 0xC4,        #   Usage (Accelerator — R2)
    0x15, 0x00,        #   Logical Minimum (0)
    0x26, 0xFF, 0x00,  #   Logical Maximum (255)
    0x75, 0x08,        #   Report Size (8)
    0x95, 0x02,        #   Report Count (2)
    0x81, 0x02,        #   Input (Data, Var, Abs)

    # D-pad (hat switch)
    0x05, 0x01,        #   Usage Page (Generic Desktop)
    0x09, 0x39,        #   Usage (Hat Switch)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x07,        #   Logical Maximum (7)
    0x35, 0x00,        #   Physical Minimum (0)
    0x46, 0x3B, 0x01,  #   Physical Maximum (315)
    0x65, 0x14,        #   Unit (Degrees)
    0x75, 0x04,        #   Report Size (4)
    0x95, 0x01,        #   Report Count (1)
    0x81, 0x42,        #   Input (Data, Var, Abs, Null)

    # 4-bit padding
    0x75, 0x04,        #   Report Size (4)
    0x95, 0x01,        #   Report Count (1)
    0x81, 0x03,        #   Input (Cnst, Var, Abs)

    0xC0,              # End Collection
])

# Report format:
#   Report ID (1 byte): 0x01
#   Buttons (2 bytes): 16 bits, little-endian
#   Left X (2 bytes): int16, little-endian
#   Left Y (2 bytes): int16, little-endian
#   Right X (2 bytes): int16, little-endian
#   Right Y (2 bytes): int16, little-endian
#   L2 (1 byte): uint8
#   R2 (1 byte): uint8
#   D-pad (1 byte): lower nibble = hat switch (0-7, 0x0F = neutral)
# Total: 14 bytes

REPORT_FORMAT: str = "<BHhhhhBBB"
REPORT_SIZE: int = struct.calcsize(REPORT_FORMAT)

# D-pad hat switch values
DPAD_NEUTRAL: int = 0x0F
DPAD_UP: int = 0
DPAD_UP_RIGHT: int = 1
DPAD_RIGHT: int = 2
DPAD_DOWN_RIGHT: int = 3
DPAD_DOWN: int = 4
DPAD_DOWN_LEFT: int = 5
DPAD_LEFT: int = 6
DPAD_UP_LEFT: int = 7

# Button bit positions
BTN_A: int = 0
BTN_B: int = 1
BTN_X: int = 2
BTN_Y: int = 3
BTN_L1: int = 4
BTN_R1: int = 5
BTN_L2: int = 6  # digital click
BTN_R2: int = 7  # digital click
BTN_SELECT: int = 8
BTN_START: int = 9
BTN_L3: int = 10
BTN_R3: int = 11
BTN_HOME: int = 12
BTN_L4: int = 13
BTN_L5: int = 14
BTN_R4: int = 15


def pack_report(
    buttons: int,
    left_x: int,
    left_y: int,
    right_x: int,
    right_y: int,
    l2: int,
    r2: int,
    dpad: int,
) -> bytes:
    """Pack controller state into an HID report.

    Args:
        buttons: 16-bit button bitmask.
        left_x: Left stick X axis (-32768 to 32767).
        left_y: Left stick Y axis (-32768 to 32767).
        right_x: Right stick X axis (-32768 to 32767).
        right_y: Right stick Y axis (-32768 to 32767).
        l2: Left trigger analog value (0-255).
        r2: Right trigger analog value (0-255).
        dpad: D-pad hat switch value (0-7, or DPAD_NEUTRAL for centered).

    Returns:
        Packed HID report bytes including report ID prefix.
    """
    buttons = buttons & 0xFFFF
    left_x = max(-32768, min(32767, left_x))
    left_y = max(-32768, min(32767, left_y))
    right_x = max(-32768, min(32767, right_x))
    right_y = max(-32768, min(32767, right_y))
    l2 = max(0, min(255, l2))
    r2 = max(0, min(255, r2))
    dpad = dpad & 0x0F

    return struct.pack(
        REPORT_FORMAT,
        0x01,     # Report ID
        buttons,
        left_x,
        left_y,
        right_x,
        right_y,
        l2,
        r2,
        dpad,
    )
