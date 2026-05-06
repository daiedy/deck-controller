# Bluetooth Debugging

Systematic Bluetooth debugging procedures for the Deck Controller plugin.

## Quick Diagnostics

Run these first to assess the situation:

```bash
# 1. Is the adapter present?
hciconfig

# 2. Is bluetoothd running?
systemctl status bluetooth

# 3. Is the adapter powered on?
bluetoothctl show | grep -E "Powered|Discoverable|Pairable|Class|Alias"

# 4. Are L2CAP sockets bound?
ss -lnp | grep l2cap

# 5. Any recent BT errors?
journalctl -u bluetooth --since "10 min ago" --priority=err
```

## Tools Reference

### btmon — HCI Traffic Monitor

Live monitor of all Bluetooth HCI traffic. Best for diagnosing connection and pairing issues.

```bash
sudo btmon
```

Filter for specific events:
```bash
sudo btmon | grep -E "HID|L2CAP|SMP|Pair"
```

Save to file for analysis:
```bash
sudo btmon -w /tmp/bt-capture.snoop
```

### dbus-monitor — BlueZ D-Bus Traffic

Monitor D-Bus messages to/from BlueZ:

```bash
dbus-monitor --system "interface='org.bluez'"
```

Filter for specific interfaces:
```bash
# Adapter changes
dbus-monitor --system "interface='org.bluez.Adapter1'"

# Device connections
dbus-monitor --system "interface='org.bluez.Device1'"

# Agent (pairing) events
dbus-monitor --system "interface='org.bluez.Agent1'"
```

### bluetoothctl — Interactive BT Management

```bash
# Show adapter info
bluetoothctl show

# List paired devices
bluetoothctl devices Paired

# Device info
bluetoothctl info <MAC_ADDRESS>

# Remove a paired device
bluetoothctl remove <MAC_ADDRESS>

# Scan for devices
bluetoothctl scan on
```

### hciconfig / hcitool

```bash
# Adapter details (address, class, flags)
hciconfig hci0

# Set device class to Gamepad
hciconfig hci0 class 0x002508

# Show current device class
hciconfig hci0 class
```

### sdptool — SDP Record Verification

```bash
# Browse local SDP records
sdptool browse local

# Look for HID profile specifically
sdptool browse local | grep -A 20 "Human Interface Device"
```

### Socket Status

```bash
# Check L2CAP listeners
ss -lnp | grep l2cap

# Check all Bluetooth sockets
ss -a | grep bluetooth
```

## Common Errors & Solutions

### "Address already in use" (EADDRINUSE) on L2CAP bind

**Cause**: bluetoothd's `input` plugin is holding PSM 17/19.

**Fix**:
```bash
# Stop bluetoothd
sudo systemctl stop bluetooth

# Restart without input plugin
sudo /usr/lib/bluetooth/bluetoothd -P input --nodetach &

# Verify PSMs are free
ss -lnp | grep l2cap
```

**Verify**: The plugin's `_restart_bluetoothd_with_plugin_flag()` should handle this automatically.

### "Permission denied" (EACCES) on socket operations

**Cause**: Not running as root.

**Fix**: Ensure `plugin.json` has `"flags": ["root"]`. L2CAP sockets on PSM < 4096 require root.

**Verify**: `whoami` should show `root` when checked from the plugin process.

### "No such device" (ENODEV)

**Cause**: Bluetooth adapter not found or powered off.

**Fix**:
```bash
# Check for adapter
hciconfig

# If adapter exists but is down
hciconfig hci0 up

# Check RF kill
rfkill list bluetooth
rfkill unblock bluetooth

# Restart Bluetooth service
sudo systemctl restart bluetooth
```

### iOS device not discovering the gamepad

**Cause**: Usually incorrect device class or HID descriptor format.

**Checklist**:
1. Device class must be `0x002508` (Peripheral | Gamepad):
   ```bash
   hciconfig hci0 class | grep "Class"
   ```
2. Adapter must be discoverable:
   ```bash
   bluetoothctl show | grep Discoverable
   ```
3. SDP record must be registered — check with `sdptool browse local`
4. HID descriptor must use proper Usage Page (0x01) and Usage (0x05 Gamepad)
5. iOS requires `HIDNormallyConnectable: True` in SDP record

### Android pairing fails

**Cause**: Missing NoInputNoOutput agent or incorrect pairing capability.

**Checklist**:
1. Verify agent is registered via D-Bus:
   ```bash
   dbus-monitor --system "interface='org.bluez.AgentManager1'"
   ```
2. Agent capability must be `NoInputNoOutput` (no PIN)
3. Device must be set as `Pairable`:
   ```bash
   bluetoothctl show | grep Pairable
   ```

### Connection drops immediately after pairing

**Cause**: L2CAP accept not happening fast enough, or socket not listening.

**Checklist**:
1. L2CAP sockets are listening:
   ```bash
   ss -lnp | grep l2cap
   ```
2. Both PSM 17 AND PSM 19 must be listening
3. Check btmon for L2CAP connection events and any error responses
4. Check if the accept loop task is running (look for accept task in plugin logs)

### HID reports not being received by target device

**Cause**: Reports sent on wrong channel, wrong format, or connection lost.

**Checklist**:
1. Reports must be sent on PSM 19 (interrupt channel), NOT PSM 17
2. Report must start with `0xA1` header byte (DATA | INPUT)
3. Report must include Report ID `0x01` as first byte after header
4. Check socket is still connected (send may silently fail if peer disconnected)
5. Monitor with btmon — look for ACL Data packets

### High input latency

**Checklist**:
1. Check polling rate in config: `cat ~/homebrew/settings/deck-controller/config.json | grep polling_rate`
2. Verify `MSG_DONTWAIT` flag on socket sends
3. Check CPU usage: `htop` (filter for python/bluetoothd)
4. Check for Bluetooth interference (WiFi on same 2.4GHz band)
5. Reduce socket buffer: tune `SO_SNDBUF`

## Log Collection

Collect comprehensive logs for bug reports:

```bash
# Bluetooth daemon logs
journalctl -u bluetooth --since "15 min ago" > /tmp/bt-daemon.log

# DeckyLoader/plugin logs
journalctl -u plugin_loader --since "15 min ago" > /tmp/plugin.log

# System info
hciconfig hci0 > /tmp/bt-adapter.log
bluetoothctl show >> /tmp/bt-adapter.log
ss -lnp | grep l2cap >> /tmp/bt-adapter.log
sdptool browse local >> /tmp/bt-adapter.log 2>&1

# Package into one archive
tar czf /tmp/deck-controller-debug.tar.gz /tmp/bt-daemon.log /tmp/plugin.log /tmp/bt-adapter.log
```

## Diagnostic Flowchart

```
Plugin won't start broadcasting
├── Is bluetoothd running? → systemctl status bluetooth
│   └── No → systemctl start bluetooth
├── Is adapter present? → hciconfig
│   └── No → rfkill unblock bluetooth; hciconfig hci0 up
├── Are PSMs free? → ss -lnp | grep l2cap
│   └── No → Restart bluetoothd with -P input
├── Is SDP record registered? → sdptool browse local
│   └── No → Check _register_sdp_record() in logs
└── Is adapter discoverable? → bluetoothctl show
    └── No → Check _set_adapter_property() in logs
```
