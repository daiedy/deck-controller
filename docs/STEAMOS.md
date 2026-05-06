# SteamOS Constraints and Workarounds

This document describes the SteamOS-specific constraints that affect Deck Controller and the strategies used to work within them.

## Read-Only Root Filesystem

SteamOS 3.x uses an immutable, A/B root filesystem partition scheme:

- `/` is mounted read-only (a btrfs snapshot)
- System updates replace the entire root partition via an A/B swap
- Any modifications to the root filesystem are lost on the next update
- `steamos-readonly disable` can make it writable, but this breaks the update mechanism

**Implication for Deck Controller**: system packages cannot be installed, system configuration files cannot be modified permanently, and all plugin files must reside in user-writable paths.

## Writable Paths

The following directories are writable and persist across reboots:

| Path | Purpose | Survives Updates |
|------|---------|-----------------|
| `~/homebrew/` | DeckyLoader plugins, settings, data | Yes |
| `~/homebrew/plugins/<name>/` | Plugin code and assets | Yes |
| `~/homebrew/settings/<name>/` | Plugin configuration files | Yes |
| `/tmp/` | Temporary files | No (cleared on reboot) |
| `/var/` | Variable state data | Partially (some subdirs persist) |
| `~/.local/` | User-local data | Yes |

Deck Controller uses:

- **Plugin code**: `~/homebrew/plugins/deck-controller/` — contains `main.py`, `backend/`, `assets/`, `defaults/`, and frontend `dist/`
- **Configuration**: `~/homebrew/settings/deck-controller/config.json` — user settings, merged with `defaults/defaults.json` at runtime
- **Logs**: routed through `decky.logger` into DeckyLoader's log infrastructure

## bluetoothd Management

BlueZ's `bluetoothd` daemon runs as a systemd service. Its built-in **input plugin** conflicts with HID device emulation because it tries to handle incoming HID connections itself.

### Activation Sequence

```
1. systemctl stop bluetooth          # Stop the default bluetoothd
2. /usr/lib/bluetooth/bluetoothd \
   -P input --nodetach               # Restart without input plugin
3. hciconfig hci0 class 0x002508     # Set device class to Gamepad
4. bluetoothctl discoverable on      # Enable discovery
5. bluetoothctl pairable on          # Enable pairing
6. bluetoothctl agent NoInputNoOutput # Register PIN-less agent
```

This causes a ~2-second delay while `bluetoothd` restarts. During this window, existing Bluetooth connections (audio devices, external controllers) are dropped.

### Deactivation Sequence

```
1. pkill -f "bluetoothd.*-P input"   # Kill our custom bluetoothd
2. systemctl start bluetooth         # Restore the systemd service
```

This restores the default BlueZ configuration. Previously paired devices will reconnect automatically.

### Why Not Modify bluetoothd Configuration

- `/etc/bluetooth/main.conf` is on the read-only root filesystem
- Modifications would be lost on the next SteamOS update
- The runtime `-P input` flag achieves the same effect without persistent changes
- The plugin handles this transparently — users never interact with bluetoothd directly

## DeckyLoader Plugin Model

DeckyLoader provides the plugin runtime:

- **Entry point**: `main.py` must contain a `Plugin` class with `_main()`, `_unload()`, and optional `_uninstall()` lifecycle methods
- **Root access**: enabled via `"flags": ["root"]` in `plugin.json` — required for `EVIOCGRAB`, `hciconfig`, `systemctl`, and L2CAP socket binding on privileged PSMs
- **RPC**: frontend calls backend methods via `callable()` from `@decky/api`, which maps to `async def` methods on the `Plugin` class
- **Events**: `decky.emit()` sends events from backend to frontend (used for status change notifications)
- **Python runtime**: DeckyLoader provides Python 3.10+ and manages the plugin process lifecycle
- **Frontend**: `dist/` contains the Rollup-bundled React app, loaded into Steam's CEF (Chromium Embedded Framework) browser

### Plugin Lifecycle

| Method | When Called | Purpose |
|--------|-----------|---------|
| `_main()` | Plugin loaded (Steam starts or plugin installed) | Initialize Config, BTHIDService, InputReader |
| `_unload()` | Plugin disabled or Steam shuts down | Stop input reading, close BT sockets, restore bluetoothd |
| `_uninstall()` | Plugin removed from DeckyLoader | Same as `_unload()` plus any cleanup |

Clean shutdown in `_unload()` is critical — failing to restore `bluetoothd` would leave Bluetooth in a broken state until the next reboot.

## Dependency Bundling

Since the root filesystem is read-only, Python packages cannot be installed via `pip` system-wide. Instead:

- **`evdev`**: must be available in the DeckyLoader Python environment or bundled in `py_modules/`
- **Standard library modules**: `socket`, `struct`, `asyncio`, `subprocess`, `json`, `os`, `threading`, `logging`, `xml.etree.ElementTree` — all available in Python 3.10+ stdlib
- **`dasbus`/`dbus-python`**: not currently used — BlueZ interaction is done via `subprocess` calls to `bluetoothctl`, `hciconfig`, and `sdptool` to avoid complex D-Bus library dependencies

If a dependency is not available in the DeckyLoader Python environment:

```bash
# On the Steam Deck, install into py_modules/
cd ~/homebrew/plugins/deck-controller
pip install --target=py_modules evdev
```

Then add `py_modules/` to the Python path in `main.py` if needed.

## Configuration Persistence

Configuration is stored as JSON at `~/homebrew/settings/deck-controller/config.json`:

```json
{
  "controller_name": "Deck Controller",
  "auto_connect": false,
  "polling_rate_hz": 250,
  "deadzone": 0.05,
  "enable_gyro": false,
  "enable_trackpads": false,
  "bt_device_class": "0x002508",
  "max_connections": 1
}
```

The `Config` class in `backend/config.py`:

1. Loads defaults from `defaults/defaults.json` (bundled with the plugin)
2. Merges with user settings from the settings directory
3. User settings override defaults
4. `Config.save()` writes back to the settings directory
5. The settings directory is created automatically via `os.makedirs(..., exist_ok=True)`

The `DECKY_PLUGIN_SETTINGS_DIR` environment variable (set by DeckyLoader) points to the settings directory. If not set, it falls back to `~/homebrew/settings/deck-controller`.

## Surviving SteamOS Updates

SteamOS updates replace the root filesystem but preserve:

- `~/homebrew/` (the entire DeckyLoader installation)
- `~/.local/`, `~/.config/`, and other user-home directories

After an update:

- DeckyLoader itself may need to be reinstalled if Valve changes the CEF injection mechanism
- Once DeckyLoader is running, all plugins in `~/homebrew/plugins/` are automatically loaded
- Plugin settings in `~/homebrew/settings/` are preserved
- The plugin re-performs the `bluetoothd` restart at activation time, so it adapts to any BlueZ version changes in the update
- `hciconfig` and `bluetoothctl` paths are standard and unlikely to change

## Known Limitations

| Limitation | Cause | Impact |
|-----------|-------|--------|
| ~2s activation delay | `bluetoothd` restart required | Brief period with no Bluetooth service |
| Existing BT connections drop | `systemctl stop bluetooth` kills all connections | Audio devices, controllers, etc. disconnect |
| Cannot install system packages | Read-only root | Dependencies must be bundled in `py_modules/` |
| No persistent `bluetoothd` config | `/etc/bluetooth/main.conf` is read-only | Must apply runtime flags on every activation |
| Plugin requires root | `EVIOCGRAB`, privileged PSM sockets, systemctl | Cannot run as a non-root plugin |
| Single HCI adapter | Steam Deck has one Bluetooth chip | Cannot dedicate a separate adapter for gamepad emulation |
