# ADR-002: SteamOS Filesystem Strategy

## Status

Accepted

## Date

2024-11-01

## Context

SteamOS 3.x uses an immutable A/B root filesystem. The root partition is mounted read-only and replaced entirely during system updates. This creates constraints for any software that needs to:

- Modify system configuration (e.g., `/etc/bluetooth/main.conf`)
- Install system packages (e.g., `pacman -S python-evdev`)
- Register system services
- Persist state across reboots and updates

Deck Controller needs to:

1. Disable BlueZ's input plugin (normally configured in `/etc/bluetooth/main.conf`)
2. Use Python libraries (`evdev`) not included in the base SteamOS image
3. Store user configuration that persists across reboots and SteamOS updates
4. Run with root privileges for Bluetooth and input device access

## Decision

Use **runtime-only modifications** that are applied each time the plugin activates and reversed when it deactivates. Persist all user data in the DeckyLoader-managed `~/homebrew/` directory tree.

Specifically:

1. **bluetoothd**: instead of editing `/etc/bluetooth/main.conf` to disable the input plugin, stop the systemd service and restart `bluetoothd` manually with the `-P input` flag at activation time. Restore the systemd service at deactivation time.

2. **Dependencies**: bundle any required Python packages in `py_modules/` within the plugin directory (`~/homebrew/plugins/deck-controller/py_modules/`). Use Python stdlib modules wherever possible — `socket`, `struct`, `subprocess`, `asyncio`, `json`, `os` — to minimize bundling needs.

3. **Configuration**: store user settings at `~/homebrew/settings/deck-controller/config.json`, which is within the DeckyLoader settings directory. Load defaults from `defaults/defaults.json` bundled with the plugin and merge with user overrides at runtime.

4. **Plugin code**: all source code lives in `~/homebrew/plugins/deck-controller/`, which is writable and survives SteamOS updates.

5. **BlueZ interaction**: use CLI tools (`bluetoothctl`, `hciconfig`, `sdptool`) via `subprocess` rather than D-Bus libraries. These tools are part of the BlueZ package installed on SteamOS and are available at their standard paths regardless of root filesystem state.

## Alternatives Considered

### Disable Read-Only Root (`steamos-readonly disable`)

Make the root filesystem writable and install packages / modify configs normally.

- **Pros**: full system access; can install packages via `pacman`; can edit `/etc/bluetooth/main.conf` permanently
- **Cons**: **breaks SteamOS updates**. The update mechanism relies on the A/B partition scheme and expects the active root to be unmodified. Users who disable read-only mode may lose their changes or fail to update. This is not a viable recommendation for end users.

### OverlayFS

Layer a writable overlay on top of the read-only root to capture modifications.

- **Pros**: changes appear persistent without modifying the underlying partition
- **Cons**: fragile across updates — the overlay must be re-applied if the lower layer changes. SteamOS does not officially support user-managed overlays. Increases complexity and potential for boot failures.

### Flatpak / Containerized Bluetooth Stack

Run a custom BlueZ instance inside a container or Flatpak with its own configuration.

- **Pros**: completely isolated from the system Bluetooth stack
- **Cons**: Bluetooth hardware access from containers is complex (requires D-Bus passthrough and device access). Running two BlueZ instances simultaneously causes conflicts. Flatpak sandboxing restricts the low-level access needed for L2CAP sockets and `EVIOCGRAB`.

### Pre-Built Binary with Static Dependencies

Compile a single statically-linked binary (e.g., in Rust or Go) that includes all dependencies.

- **Pros**: no runtime dependency issues; single file deployment
- **Cons**: DeckyLoader's plugin model requires a Python entry point (`main.py` with a `Plugin` class). A compiled binary would need to be launched as a subprocess, adding complexity. Would not eliminate the need for runtime `bluetoothd` management.

## Consequences

### Positive

- **Survives SteamOS updates** — no modifications to the root filesystem; everything is in `~/homebrew/`
- **Clean activation/deactivation** — state is applied at runtime and cleaned up on shutdown; no persistent side effects
- **Standard DeckyLoader conventions** — settings path, plugin directory structure, and lifecycle hooks follow established patterns
- **Minimal system coupling** — relies only on BlueZ CLI tools (`bluetoothctl`, `hciconfig`, `sdptool`) that are part of the standard SteamOS install

### Negative

- **~2-second activation delay** — restarting `bluetoothd` takes time; users must wait briefly after pressing "Start Broadcasting"
- **Existing Bluetooth connections drop** — stopping `bluetooth.service` disconnects all active Bluetooth devices (audio, controllers); they reconnect after deactivation
- **Must restore state on deactivation** — if the plugin crashes without calling `_unload()`, `bluetoothd` remains in the modified state until the next reboot. DeckyLoader's crash handling partially mitigates this.
- **Dependency bundling burden** — any Python package not in SteamOS's base image must be manually bundled in `py_modules/` and kept up to date
