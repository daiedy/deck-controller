"""HID Report Descriptor and report packing for Xbox-compatible gamepad layout."""

from __future__ import annotations

import struct

# Xbox-compatible gamepad HID Report Descriptor
# Report ID: 0x01
# Layout:
#   - 20 buttons (3 bytes: 20 bits + 4-bit padding)
#   - Left stick X, Y + Right stick X, Y (4 x int16)
#   - L2, R2 triggers (2 x uint8)
#   - D-pad hat switch (4-bit) + 4-bit padding
GAMEPAD_REPORT_DESCRIPTOR: bytes = bytes([
    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x05,        # Usage (Gamepad)
    0xA1, 0x01,        # Collection (Application)
    0x85, 0x01,        #   Report ID (1)

    # 20 buttons
    0x05, 0x09,        #   Usage Page (Button)
    0x19, 0x01,        #   Usage Minimum (1)
    0x29, 0x14,        #   Usage Maximum (20)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x01,        #   Logical Maximum (1)
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x14,        #   Report Count (20)
    0x81, 0x02,        #   Input (Data, Var, Abs)

    # 4-bit padding to byte-align buttons
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x04,        #   Report Count (4)
    0x81, 0x03,        #   Input (Cnst, Var, Abs)

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

# Mouse HID Report Descriptor
# Report ID: 0x02
# Layout:
#   - 3 buttons (1 bit each + 5 bits padding)
#   - X, Y relative movement (int8 each)
#   - Scroll wheel (int8)
MOUSE_REPORT_DESCRIPTOR: bytes = bytes([
    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x02,        # Usage (Mouse)
    0xA1, 0x01,        # Collection (Application)
    0x85, 0x02,        #   Report ID (2)
    0x09, 0x01,        #   Usage (Pointer)
    0xA1, 0x00,        #   Collection (Physical)

    # 3 buttons
    0x05, 0x09,        #     Usage Page (Button)
    0x19, 0x01,        #     Usage Minimum (1)
    0x29, 0x03,        #     Usage Maximum (3)
    0x15, 0x00,        #     Logical Minimum (0)
    0x25, 0x01,        #     Logical Maximum (1)
    0x75, 0x01,        #     Report Size (1)
    0x95, 0x03,        #     Report Count (3)
    0x81, 0x02,        #     Input (Data, Var, Abs)

    # 5-bit padding
    0x75, 0x05,        #     Report Size (5)
    0x95, 0x01,        #     Report Count (1)
    0x81, 0x03,        #     Input (Cnst, Var, Abs)

    # X, Y relative movement
    0x05, 0x01,        #     Usage Page (Generic Desktop)
    0x09, 0x30,        #     Usage (X)
    0x09, 0x31,        #     Usage (Y)
    0x15, 0x81,        #     Logical Minimum (-127)
    0x25, 0x7F,        #     Logical Maximum (127)
    0x75, 0x08,        #     Report Size (8)
    0x95, 0x02,        #     Report Count (2)
    0x81, 0x06,        #     Input (Data, Var, Rel)

    # Scroll wheel
    0x09, 0x38,        #     Usage (Wheel)
    0x15, 0x81,        #     Logical Minimum (-127)
    0x25, 0x7F,        #     Logical Maximum (127)
    0x75, 0x08,        #     Report Size (8)
    0x95, 0x01,        #     Report Count (1)
    0x81, 0x06,        #     Input (Data, Var, Rel)

    0xC0,              #   End Collection (Physical)
    0xC0,              # End Collection (Application)
])

# Motion Sensor (Vendor-Specific) HID Report Descriptor
# Report ID: 0x03
# Layout: 6 × int16 (gyro X, Y, Z + accel X, Y, Z) = 12 bytes data
MOTION_REPORT_DESCRIPTOR: bytes = bytes([
    0x06, 0x00, 0xFF,  # Usage Page (Vendor Specific 0xFF00)
    0x09, 0x01,        # Usage (Vendor Usage 1)
    0xA1, 0x01,        # Collection (Application)
    0x85, 0x03,        #   Report ID (3)

    # Gyroscope X, Y, Z — int16 (angular velocity)
    0x09, 0x21,        #   Usage (Vendor: Gyro X)
    0x09, 0x22,        #   Usage (Vendor: Gyro Y)
    0x09, 0x23,        #   Usage (Vendor: Gyro Z)
    # Accelerometer X, Y, Z — int16 (linear acceleration)
    0x09, 0x24,        #   Usage (Vendor: Accel X)
    0x09, 0x25,        #   Usage (Vendor: Accel Y)
    0x09, 0x26,        #   Usage (Vendor: Accel Z)

    0x16, 0x00, 0x80,  #   Logical Minimum (-32768)
    0x26, 0xFF, 0x7F,  #   Logical Maximum (32767)
    0x75, 0x10,        #   Report Size (16)
    0x95, 0x06,        #   Report Count (6)
    0x81, 0x02,        #   Input (Data, Var, Abs)

    0xC0,              # End Collection
])

# Composite descriptor: Gamepad + Mouse + Motion
COMPOSITE_REPORT_DESCRIPTOR: bytes = (
    GAMEPAD_REPORT_DESCRIPTOR + MOUSE_REPORT_DESCRIPTOR + MOTION_REPORT_DESCRIPTOR
)

# Report format:
#   Report ID (1 byte): 0x01
#   Buttons (3 bytes): 20 bits little-endian + 4 bits padding
#   Left X (2 bytes): int16, little-endian
#   Left Y (2 bytes): int16, little-endian
#   Right X (2 bytes): int16, little-endian
#   Right Y (2 bytes): int16, little-endian
#   L2 (1 byte): uint8
#   R2 (1 byte): uint8
#   D-pad (1 byte): lower nibble = hat switch (0-7, 0x0F = neutral)
# Total: 15 bytes

_AXES_FORMAT: str = "<hhhhBBB"
REPORT_SIZE: int = 1 + 3 + struct.calcsize(_AXES_FORMAT)  # 15 bytes

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
BTN_R5: int = 16


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
        buttons: 20-bit button bitmask.
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
    buttons = buttons & 0xFFFFF  # 20 bits
    left_x = max(-32768, min(32767, left_x))
    left_y = max(-32768, min(32767, left_y))
    right_x = max(-32768, min(32767, right_x))
    right_y = max(-32768, min(32767, right_y))
    l2 = max(0, min(255, l2))
    r2 = max(0, min(255, r2))
    dpad = dpad & 0x0F

    # Pack buttons as 3 bytes (little-endian, 20 bits used + 4 bits padding)
    btn_bytes = buttons.to_bytes(3, byteorder='little')
    axes = struct.pack(_AXES_FORMAT, left_x, left_y, right_x, right_y, l2, r2, dpad)
    return b'\x01' + btn_bytes + axes


def pack_mouse_report(buttons: int, dx: int, dy: int, wheel: int) -> bytes:
    """Pack mouse state into HID report.

    Args:
        buttons: 3-bit button bitmask (bit 0=left, 1=right, 2=middle).
        dx: Relative X movement (-127 to 127).
        dy: Relative Y movement (-127 to 127).
        wheel: Scroll wheel delta (-127 to 127, positive=up).

    Returns:
        Packed HID mouse report bytes including Report ID 0x02.
    """
    buttons = buttons & 0x07
    dx = max(-127, min(127, dx))
    dy = max(-127, min(127, dy))
    wheel = max(-127, min(127, wheel))
    return struct.pack("<BBbbb", 0x02, buttons, dx, dy, wheel)


def pack_motion_report(
    gyro_x: int, gyro_y: int, gyro_z: int,
    accel_x: int, accel_y: int, accel_z: int,
) -> bytes:
    """Pack motion sensor data into HID report.

    Args:
        gyro_x/y/z: Angular velocity in device units (-32768 to 32767).
        accel_x/y/z: Linear acceleration in device units (-32768 to 32767).

    Returns:
        Packed HID motion report bytes with Report ID 0x03.
    """
    return struct.pack(
        "<Bhhhhhh",
        0x03,
        max(-32768, min(32767, gyro_x)),
        max(-32768, min(32767, gyro_y)),
        max(-32768, min(32767, gyro_z)),
        max(-32768, min(32767, accel_x)),
        max(-32768, min(32767, accel_y)),
        max(-32768, min(32767, accel_z)),
    )
