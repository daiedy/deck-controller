# Deck Controller — Copilot Instructions

## Project Overview
This is a **DeckyLoader plugin** for Steam Deck that turns it into a Bluetooth HID gamepad controller for PC, Android, and iOS/macOS.

## Architecture
- **Backend**: Python 3.10+ — `main.py` (plugin entry) + `backend/` package
- **Frontend**: React/TSX — `src/index.tsx` entry, components in `src/components/`, hooks in `src/hooks/`
- **Communication**: Frontend calls backend via `@decky/api` `callable()` RPC pattern

## Tech Stack
- **Python**: `evdev` for input reading, `dbus-python`/`dasbus` for BlueZ D-Bus, `socket` (AF_BLUETOOTH) for L2CAP
- **Frontend**: `@decky/ui` component library, `@decky/api` for plugin registration and backend RPC
- **Build**: pnpm + Rollup for frontend, Python runs directly via DeckyLoader

## SteamOS Constraints
- SteamOS is **Arch-based** with a **read-only root filesystem**
- System packages cannot be installed; bundle Python deps in `py_modules/` if needed
- BlueZ is available system-wide; `bluetoothd` may need restart with `-P input` flag
- Plugin runs with **root privileges** (flag set in `plugin.json`)

## Bluetooth HID Emulation
- Uses **BlueZ D-Bus API** for adapter management, pairing, discovery
- **L2CAP sockets** on PSM 17 (control) and PSM 19 (interrupt) for HID data
- SDP service record in `assets/gamepad_sdp.xml` defines the HID gamepad profile
- HID Report Descriptor in `backend/hid_descriptor.py` defines button/axis layout
- Pairing uses **NoInputNoOutput** agent (PIN-less) for seamless connection

## Key Paths
- Config: `~/homebrew/settings/deck-controller/config.json`
- Logs: DeckyLoader log directory via `decky.logger`
- Settings dir: `DECKY_PLUGIN_SETTINGS_DIR` environment variable
- Runtime dir: `DECKY_PLUGIN_RUNTIME_DIR` environment variable

## Conventions
- Python: type hints everywhere, asyncio for all I/O, proper error handling
- Frontend: functional components, custom hooks for state management
- Backend RPC methods return `dict` with `success` boolean and relevant data
- All cleanup must happen in `_unload()` — restore bluetoothd, close sockets, release evdev
