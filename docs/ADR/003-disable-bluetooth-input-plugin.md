# ADR 003 — Disable BlueZ input plugin & restart bluetoothd for HID emulation

Status: Accepted

Context

Deck Controller must emulate a Bluetooth HID device (gamepad). BlueZ's built-in "input" plugin interferes with binding raw L2CAP HID channels and claiming the input role. On SteamOS the system image is largely read-only which constrains how the plugin can reconfigure system services at runtime.

Decision

Restart bluetoothd with the input plugin disabled (bluetoothd -P input) and apply a transient systemd drop-in override to persist the flag while the plugin runs. Also adjust /etc/bluetooth/main.conf to set device class, AlwaysPairable and DiscoverableTimeout so the adapter advertises correctly. To work on SteamOS, toggle the read-only filesystem via `steamos-readonly disable`/`enable` while writing the override or main.conf modifications.

Rationale

- The BlueZ input plugin conflicts with acting as an HID device (server role). Disabling it removes the conflict and allows the plugin to bind PSM 17/19.
- A systemd drop-in is the least-invasive way to pass a different ExecStart to bluetoothd without replacing packages.
- Modifying main.conf ensures the adapter advertises as a gamepad and remains discoverable/pairable.
- Using `steamos-readonly` is necessary because SteamOS mounts system files as read-only; the plugin must temporarily make changes at runtime.

Consequences

- Requires root privileges and writes to system directories while the plugin runs.
- The plugin must carefully restore the systemd override and main.conf backup on shutdown to avoid persistent system changes.
- There is a small risk of leaving bluetoothd in a modified state if the plugin is terminated unexpectedly; the implementation includes helper process management and backup/restore logic.

Alternatives Considered

- Bundling a kernel-level driver or kernel module: too invasive and outside the plugin scope.
- Running a userspace shim without restarting bluetoothd: BlueZ input plugin will still conflict.
- Requiring users to manually modify systemd config: worse UX and error-prone.

Notes

See `backend/bt_hid_service.py` for the implementation details (systemd drop-in, steamos-readonly usage, main.conf backup/restore, and SDP helper process).
