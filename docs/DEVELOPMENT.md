# Development Guide

This document covers setting up a development environment, building, testing, and contributing to Deck Controller.

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Node.js | 18+ | Frontend build tooling |
| pnpm | 8+ | Package manager (required by DeckyLoader ecosystem) |
| Python | 3.10+ | Backend runtime |
| Git | 2.x | Source control |
| Steam Deck (or SteamOS VM) | — | Testing target |

## Clone and Setup

```bash
git clone https://github.com/daiedy/deck-controller.git
cd deck-controller
```

## Frontend Development

The frontend is a React 18 + TypeScript application built with Rollup.

### Install Dependencies

```bash
pnpm install
```

### Build

```bash
pnpm run build
```

This produces the bundled output in `dist/`. The build uses Rollup with the following plugins:

- `@rollup/plugin-typescript` — TypeScript compilation
- `@rollup/plugin-node-resolve` — resolves `node_modules`
- `@rollup/plugin-commonjs` — converts CJS modules to ESM
- `@rollup/plugin-json` — imports JSON files
- `@rollup/plugin-replace` — environment variable injection
- `rollup-plugin-import-css` — CSS imports

### Key Files

| File | Purpose |
|------|---------|
| `src/index.tsx` | Plugin entry — `definePlugin()` registration |
| `src/components/MainView.tsx` | Main UI — status display, start/stop controls |
| `src/components/DeviceList.tsx` | Paired device list with refresh/remove |
| `src/components/Settings.tsx` | Configuration panel |
| `src/hooks/useBackend.ts` | RPC hook — wraps `callable()` from `@decky/api` |

### UI Components

The frontend uses `@decky/ui` components (`PanelSection`, `PanelSectionRow`, `ButtonItem`, `Field`, `ToggleField`, `SliderField`, `DropdownItem`, `TextField`). These render natively inside Steam's Quick Access Menu.

## Backend Development

The backend is pure Python 3.10+ with type hints. It runs directly under DeckyLoader without a build step.

### Virtual Environment (for local development)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install evdev  # Only works on Linux
```

The `evdev` package requires Linux kernel headers and cannot be installed on macOS or Windows. For local type checking without evdev, the codebase includes an `ImportError` guard:

```python
try:
    import evdev
except ImportError:
    evdev = None
```

### Key Files

| File | Purpose |
|------|---------|
| `main.py` | `Plugin` class — lifecycle, RPC methods, wiring |
| `backend/config.py` | `Config` — thread-safe JSON config manager |
| `backend/input_reader.py` | `InputReader` — evdev controller reads |
| `backend/hid_descriptor.py` | HID report descriptor + `pack_report()` |
| `backend/bt_hid_service.py` | `BTHIDService` — BlueZ + L2CAP |
| `defaults/defaults.json` | Default configuration values |
| `assets/gamepad_sdp.xml` | SDP service record for HID gamepad |

### Running Outside DeckyLoader

The backend cannot run fully outside SteamOS (it needs `evdev`, `bluetoothctl`, `hciconfig`, and real Bluetooth hardware). For local development:

1. **Type checking**: use `mypy` or Pyright/Pylance — the codebase uses type hints throughout
2. **Unit tests**: mock `evdev` and `subprocess` calls
3. **Integration tests**: must be run on actual Steam Deck hardware

## Testing on Steam Deck

### SSH Access

Enable SSH on your Steam Deck:

1. Switch to Desktop Mode
2. Open Konsole
3. Set a password: `passwd`
4. Start SSH: `sudo systemctl start sshd`

Connect from your development machine:

```bash
ssh deck@<steam-deck-ip>
```

### Sideload Plugin

Use the Makefile to build and create a deployment zip:

```bash
make deploy
```

This produces `deck-controller.zip`. Transfer and install:

```bash
# Copy to Steam Deck
scp deck-controller.zip deck@<steam-deck-ip>:/tmp/

# On the Steam Deck
ssh deck@<steam-deck-ip>
cd ~/homebrew/plugins
mkdir -p deck-controller
cd deck-controller
unzip /tmp/deck-controller.zip

# Restart DeckyLoader
sudo systemctl restart plugin_loader
```

### Live Reload (Development)

For rapid iteration, sync files directly:

```bash
# Sync backend changes
rsync -avz --delete main.py backend/ defaults/ assets/ \
  deck@<steam-deck-ip>:~/homebrew/plugins/deck-controller/

# Sync frontend changes (after pnpm run build)
rsync -avz --delete dist/ \
  deck@<steam-deck-ip>:~/homebrew/plugins/deck-controller/dist/

# Restart plugin
ssh deck@<steam-deck-ip> "sudo systemctl restart plugin_loader"
```

## Project Structure

```
deck-controller/
├── main.py                  # Plugin entry point (Plugin class)
├── plugin.json              # DeckyLoader plugin manifest
├── package.json             # Node.js dependencies and scripts
├── rollup.config.js         # Rollup build configuration
├── tsconfig.json            # TypeScript configuration
├── Makefile                 # Build and deploy targets
├── LICENSE                  # BSD-3-Clause
├── assets/
│   └── gamepad_sdp.xml      # SDP service record
├── backend/
│   ├── __init__.py
│   ├── bt_hid_service.py    # Bluetooth HID service
│   ├── config.py            # Configuration manager
│   ├── hid_descriptor.py    # HID report descriptor + packing
│   └── input_reader.py      # evdev input reader
├── defaults/
│   └── defaults.json        # Default configuration
├── docs/
│   ├── ARCHITECTURE.md      # System architecture
│   ├── BLUETOOTH.md         # BT HID protocol reference
│   ├── DEVELOPMENT.md       # This file
│   ├── STEAMOS.md           # SteamOS constraints
│   └── ADR/
│       ├── 001-bt-hid-emulation.md
│       └── 002-steamos-filesystem.md
└── src/
    ├── index.tsx             # Frontend entry point
    ├── components/
    │   ├── MainView.tsx      # Main status + controls
    │   ├── DeviceList.tsx    # Paired device list
    │   └── Settings.tsx      # Settings panel
    └── hooks/
        └── useBackend.ts     # Backend RPC hook
```

## Contributing Workflow

1. **Fork** the repository on GitHub
2. **Clone** your fork locally
3. **Create a branch** for your feature or fix:
   ```bash
   git checkout -b feature/my-change
   ```
4. **Make changes** — follow the code style guidelines below
5. **Test** on a Steam Deck if possible
6. **Commit** with a clear message:
   ```bash
   git commit -m "feat: add rumble feedback support"
   ```
7. **Push** to your fork:
   ```bash
   git push origin feature/my-change
   ```
8. **Open a Pull Request** against `main`

### Commit Message Convention

Use conventional commits:

- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation
- `refactor:` — code restructuring without behavior change
- `chore:` — build, tooling, dependency updates

## Code Style

### Python

- **Formatter**: [Black](https://black.readthedocs.io/) with default settings (line length 88)
- **Import sorting**: [isort](https://pycqa.github.io/isort/) with `profile = "black"`
- **Type hints**: required on all function signatures and class attributes
- **Docstrings**: Google style on all public functions and classes
- **Async**: use `asyncio` for all I/O; avoid `time.sleep()` in async code

```bash
# Format
black main.py backend/
isort main.py backend/

# Type check
mypy main.py backend/ --ignore-missing-imports
```

### TypeScript

- **Formatter**: [Prettier](https://prettier.io/) with default settings
- **Components**: functional components with hooks (no class components)
- **Imports**: named imports from `@decky/ui` and `@decky/api`

```bash
# Format
npx prettier --write src/
```

## Debug Mode

DeckyLoader provides debug logging. The plugin registers `"debug"` in `plugin.json` flags, which enables verbose log output.

View logs:

```bash
# On the Steam Deck
journalctl -u plugin_loader -f

# Or via DeckyLoader's built-in log viewer in the developer settings
```

The plugin logs to `decky.logger`, which routes to DeckyLoader's log infrastructure. Key log points:

- `"Deck Controller plugin loading..."` — `_main()` entry
- `"Found controller: <name> at <path>"` — evdev device discovery
- `"Grabbed device exclusively"` — EVIOCGRAB success
- `"bluetoothd restarted with -P input"` — bluetoothd management
- `"L2CAP sockets opened on PSM 17 and 19"` — socket setup
- `"Device connected: <name> (<address>)"` — successful pairing
- `"Failed to send HID report: <error>"` — transmission errors
