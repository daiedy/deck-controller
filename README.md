# 🎮 Deck Controller

[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](LICENSE)
[![DeckyLoader](https://img.shields.io/badge/DeckyLoader-Plugin-orange)](https://decky.xyz)
[![SteamOS](https://img.shields.io/badge/SteamOS-3.x-1a9fff)](https://store.steampowered.com/steamos)

**Turn your Steam Deck into a wireless Bluetooth gamepad for any device.**

Deck Controller is a [DeckyLoader](https://decky.xyz) plugin that emulates a standard Bluetooth HID gamepad, letting you use your Steam Deck's built-in controls to play games on a PC, Android phone, iPhone, iPad, Mac, or Apple TV — no extra hardware needed.

---

## Features

- **Bluetooth gamepad emulation** — appears as a standard HID gamepad to any host device
- **Cross-platform** — works with Windows, Android, iOS 13+, and macOS
- **Low latency** — direct evdev reads + L2CAP sockets for ~10–20 ms end-to-end
- **Full control mapping** — analog sticks, triggers, d-pad, 16 buttons including Steam Deck extras (L4, L5, R4)
- **Customizable** — adjustable deadzone, polling rate, controller name
- **No extra hardware** — uses the Steam Deck's built-in Bluetooth radio
- **Seamless pairing** — PIN-less NoInputNoOutput agent for one-tap connections

## Architecture

```mermaid
flowchart LR
    subgraph SteamDeck["Steam Deck"]
        UI["Frontend<br/>(React/TSX)"]
        RPC["@decky/api<br/>callable() RPC"]
        Plugin["main.py<br/>Plugin class"]
        IR["InputReader<br/>(evdev)"]
        HD["pack_report()<br/>(HID descriptor)"]
        BT["BTHIDService<br/>(BlueZ + L2CAP)"]
        Controller["Built-in<br/>Controller"]
    end
    Target["Target Device<br/>(PC / Android / iOS / macOS)"]

    Controller -->|evdev events| IR
    IR -->|InputState callback| Plugin
    Plugin -->|pack_report()| HD
    HD -->|14-byte HID report| BT
    BT -->|L2CAP PSM 19| Target
    UI -->|RPC| RPC
    RPC -->|callable()| Plugin
```

## Supported Platforms

| Platform | Status | Notes |
|----------|--------|-------|
| Windows 10/11 | ✅ Supported | Recognized as standard Xbox-style gamepad |
| Android 9+ | ✅ Supported | Works with most games and emulators |
| iOS 13+ | ✅ Supported | Requires GameController framework support in the app |
| macOS 11+ | ✅ Supported | Works with native and Steam games |
| Linux | ✅ Supported | Standard HID gamepad via BlueZ |

## Installation

### From Decky Plugin Store (Recommended)

1. Install [DeckyLoader](https://decky.xyz) on your Steam Deck
2. Open the Decky menu (QAM → plug icon)
3. Go to the Plugin Store
4. Search for **"Deck Controller"**
5. Click **Install**

### Manual Install

```bash
# SSH into your Steam Deck
ssh deck@steamdeck

# Clone the repository
git clone https://github.com/daiedy/deck-controller.git /tmp/deck-controller
cd /tmp/deck-controller

# Build the plugin
make build

# Deploy to DeckyLoader plugins directory
cp -r dist defaults assets plugin.json main.py backend \
  ~/homebrew/plugins/deck-controller/

# Restart DeckyLoader
sudo systemctl restart plugin_loader
```

## Usage

1. Open the **Decky menu** on your Steam Deck (press the `...` button → plug icon)
2. Select **Deck Controller** from the plugin list
3. Press **Start Broadcasting** — the Steam Deck enters Bluetooth discoverable mode
4. On your target device, open Bluetooth settings and pair with **"Deck Controller"**
5. Once connected, the status indicator turns green and the Steam Deck's controls are forwarded as gamepad input
6. Press **Stop Broadcasting** to disconnect and restore normal Steam Deck operation

## Configuration

All settings are accessible through the plugin's Settings panel in the Decky menu.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `controller_name` | string | `"Deck Controller"` | Bluetooth name advertised to other devices |
| `auto_connect` | boolean | `false` | Automatically reconnect to the last paired device on plugin load |
| `polling_rate_hz` | integer | `250` | Input polling frequency in Hz (125, 250, or 500) |
| `deadzone` | float | `0.05` | Analog stick deadzone threshold (0.0–0.25) |
| `enable_gyro` | boolean | `false` | Forward gyroscope data (experimental) |
| `enable_trackpads` | boolean | `false` | Forward trackpad input (experimental) |
| `bt_device_class` | string | `"0x002508"` | Bluetooth device class (gamepad) |
| `max_connections` | integer | `1` | Maximum simultaneous Bluetooth connections |

Configuration is stored at `~/homebrew/settings/deck-controller/config.json` and persists across reboots.

## How It Works

1. **Input capture** — `InputReader` uses Linux `evdev` to read raw events from the Steam Deck's built-in controller (identified by device name patterns). The device is grabbed exclusively (`EVIOCGRAB`) to prevent duplicate input in Steam.

2. **HID translation** — Button presses, stick axes, triggers, and d-pad are normalized into a 14-byte HID report using an Xbox-compatible report descriptor. The report includes 16 buttons, 4 axes (16-bit signed), 2 triggers (8-bit unsigned), and a 4-bit hat switch.

3. **Bluetooth transmission** — `BTHIDService` restarts `bluetoothd` with the `-P input` flag to disable BlueZ's input plugin (which would conflict), registers an SDP service record describing a gamepad profile, and opens two L2CAP sockets: PSM 17 (control) and PSM 19 (interrupt). HID reports are sent on the interrupt channel prefixed with `0xA1` (DATA|INPUT).

4. **Pairing** — A `NoInputNoOutput` agent handles pairing without requiring a PIN, enabling seamless one-tap connections from the target device.

## Limitations

- **Single connection** — only one device can be connected at a time (Bluetooth Classic HID constraint)
- **Existing Bluetooth devices disconnect** — activating broadcasting restarts `bluetoothd`, which temporarily drops any active Bluetooth connections (audio, controllers, etc.)
- **Latency** — approximately 10–20 ms end-to-end (evdev read ~0.5 ms + HID encode ~0.01 ms + L2CAP send ~0.5 ms + BT radio ~5–10 ms)
- **SteamOS updates** — plugins survive updates but `bluetoothd` may need re-patching; the plugin handles this automatically at activation time
- **Gyro/trackpads** — marked experimental; not yet included in the HID report descriptor

## Development

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for build instructions, project structure, and contribution workflow.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — system design, components, and data flow
- [Bluetooth HID Protocol](docs/BLUETOOTH.md) — BT profile details, SDP, L2CAP, report descriptor
- [SteamOS Constraints](docs/STEAMOS.md) — filesystem, bluetoothd, dependency bundling
- [Development Guide](docs/DEVELOPMENT.md) — setup, build, deploy, contribute
- [ADR-001: BT HID Emulation](docs/ADR/001-bt-hid-emulation.md) — why BlueZ + L2CAP
- [ADR-002: SteamOS Filesystem](docs/ADR/002-steamos-filesystem.md) — runtime-only modifications strategy

## License

[BSD-3-Clause](LICENSE) © 2024–2026 daiedy

## Acknowledgements

- [BlueZ](http://www.bluez.org/) — the official Linux Bluetooth stack
- [DeckyLoader](https://decky.xyz) — the plugin framework that makes this possible
- [python-evdev](https://python-evdev.readthedocs.io/) — Python bindings for the Linux input subsystem
- [Valve](https://www.valvesoftware.com/) — for the Steam Deck and SteamOS
