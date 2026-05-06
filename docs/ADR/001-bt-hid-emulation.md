# ADR-001: Bluetooth HID Emulation Strategy

## Status

Accepted

## Date

2024-11-01

## Context

Deck Controller needs to make the Steam Deck appear as a standard Bluetooth gamepad to external devices (PC, Android, iOS, macOS). The emulation must:

- Work over Bluetooth without any cables or additional hardware
- Be recognized as a standard HID gamepad by all major operating systems
- Operate within SteamOS constraints (read-only root filesystem, no persistent system modifications)
- Achieve low enough latency for real-time gaming (< 20 ms)
- Support PIN-less pairing for a seamless user experience

## Decision

Use **BlueZ D-Bus/CLI tools for Bluetooth adapter management** combined with **direct L2CAP sockets for HID data transport**, with an **SDP service record** describing a standard HID gamepad profile.

Specifically:

1. **BlueZ CLI tools** (`bluetoothctl`, `hciconfig`, `sdptool`) to configure the adapter — set device class, discoverable mode, pairing agent, and register the SDP record. This avoids heavy D-Bus library dependencies (`dbus-python`, `dasbus`) that would need to be bundled.

2. **Raw L2CAP sockets** (`AF_BLUETOOTH`, `SOCK_SEQPACKET`, `BTPROTO_L2CAP`) on PSM 17 (control) and PSM 19 (interrupt) for HID data. Python's `socket` module supports `AF_BLUETOOTH` natively — no additional dependencies.

3. **SDP service record** in XML (`assets/gamepad_sdp.xml`) declaring the HID service UUID (`0x1124`), device subclass (gamepad), and L2CAP PSMs. Registered via `sdptool`.

4. **HID Report Descriptor** in binary (`backend/hid_descriptor.py`) defining an Xbox-compatible gamepad layout with 16 buttons, 4 axes, 2 triggers, and a hat switch.

5. **bluetoothd restart** with `-P input` flag to disable BlueZ's built-in input plugin, which conflicts with HID device emulation.

## Alternatives Considered

### UHID Kernel Interface

Create a virtual HID device via `/dev/uhid` and let the kernel handle Bluetooth HID hosting.

- **Pros**: cleaner separation; kernel handles HID protocol details
- **Cons**: UHID is designed for creating *local* HID devices (e.g., virtual keyboards), not for *remote* Bluetooth HID device emulation. There is no established path from UHID to Bluetooth HID device role. Would require a custom kernel module or significant BlueZ patching.

### Bluetooth Low Energy (BLE) HID over GATT

Use BLE's HID over GATT profile instead of Classic Bluetooth HID.

- **Pros**: lower power consumption; potentially simpler pairing
- **Cons**: iOS's GameController framework has limited support for BLE HID gamepads (it primarily supports MFi controllers and Bluetooth Classic HID). Latency can be higher with BLE due to connection interval constraints. BLE throughput is lower, which matters for high-frequency input reports at 250+ Hz.

### USB Gadget Mode

Use the Steam Deck's USB-C port in gadget mode to emulate a USB HID gamepad.

- **Pros**: zero wireless latency; universally compatible
- **Cons**: requires a physical cable, defeating the wireless use case. USB gadget mode may conflict with Steam Deck's USB-C charging and docking functionality.

### Existing Projects (bthidd, bluetooth-hid-emulator)

Fork or integrate an existing Bluetooth HID emulation project.

- **Pros**: proven implementations
- **Cons**: most existing projects are unmaintained, target desktop Linux (not SteamOS), require system package installation, or depend on deprecated BlueZ APIs. None integrate with DeckyLoader's plugin model.

## Consequences

### Positive

- **Cross-platform compatibility** — standard Bluetooth HID is supported by every major OS
- **No additional hardware** — uses the Steam Deck's built-in Bluetooth radio
- **Low latency** — direct L2CAP sockets with minimal Python overhead (~10–20 ms total)
- **Minimal dependencies** — only `evdev` (for input reading) beyond Python stdlib; BlueZ interaction via CLI tools avoids library bundling
- **Seamless pairing** — `NoInputNoOutput` agent enables one-tap connections

### Negative

- **bluetoothd restart required** — must stop and restart `bluetoothd` with `-P input`, causing a ~2-second gap where all Bluetooth connections drop
- **Existing Bluetooth devices disconnect** — audio devices, external controllers, etc. lose connection during broadcasting and must reconnect after stopping
- **Root privileges required** — binding L2CAP sockets on PSM 17/19 (privileged ports < 1024), `EVIOCGRAB`, `systemctl`, and `hciconfig` all need root access
- **Single connection limit** — the current L2CAP accept loop handles one device at a time; supporting multiple connections would require architectural changes
