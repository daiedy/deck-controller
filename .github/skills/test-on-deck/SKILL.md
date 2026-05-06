# Test on Steam Deck

How to deploy and test the Deck Controller plugin on a real Steam Deck.

## Prerequisites

- Steam Deck with **DeckyLoader** installed ([install guide](https://github.com/SteamDeckHomebrew/decky-loader))
- **SSH access** to the Deck:
  1. On Deck: Steam > Settings > System > Enable Developer Mode
  2. On Deck: Settings > Developer > Enable SSH
  3. Set a password: open Konsole in Desktop Mode, run `passwd`
- Deck's IP address: Settings > Internet > connection details, or run `ip addr` on Deck
- Plugin built locally: `make build` (see `build-plugin` skill)

## Deploy Plugin

### Full Deploy

```bash
DECK_IP="<your-deck-ip>"

rsync -avz \
  --exclude node_modules \
  --exclude .git \
  --exclude out \
  --exclude '*.zip' \
  . deck@${DECK_IP}:~/homebrew/plugins/deck-controller/
```

### Frontend-Only Deploy

After changing only `src/` files:

```bash
pnpm run build
rsync -avz dist/ deck@${DECK_IP}:~/homebrew/plugins/deck-controller/dist/
```

### Backend-Only Deploy

After changing only `main.py` or `backend/`:

```bash
rsync -avz main.py backend/ deck@${DECK_IP}:~/homebrew/plugins/deck-controller/
```

## Restart DeckyLoader

After deploying, restart the plugin loader to pick up changes:

```bash
ssh deck@${DECK_IP} "sudo systemctl restart plugin_loader"
```

Or from the Deck: DeckyLoader menu > Settings > Reload.

## View Logs

### DeckyLoader logs (plugin lifecycle + Python output)

```bash
ssh deck@${DECK_IP} "journalctl -u plugin_loader -f"
```

### Bluetooth logs

```bash
ssh deck@${DECK_IP} "journalctl -u bluetooth -f"
```

### Filter for this plugin only

```bash
ssh deck@${DECK_IP} "journalctl -u plugin_loader -f" | grep -i "deck.controller\|deck-controller"
```

## Frontend Hot Reload Workflow

1. Edit files in `src/`
2. `pnpm run build`
3. `rsync -avz dist/ deck@${DECK_IP}:~/homebrew/plugins/deck-controller/dist/`
4. On Deck: press the Steam button, navigate away from the plugin, navigate back — or restart Steam

## Debug Python Backend

1. SSH into the Deck: `ssh deck@${DECK_IP}`
2. Check if the plugin loaded: `journalctl -u plugin_loader --since "5 min ago" | grep deck`
3. For interactive debugging, add logging:
   ```python
   import decky
   decky.logger.info("Debug: variable = %s", variable)
   ```
4. Restart and check logs

## Bluetooth Debugging on Deck

```bash
# Check adapter status
ssh deck@${DECK_IP} "bluetoothctl show"

# Monitor BT HCI traffic (requires root)
ssh deck@${DECK_IP} "sudo btmon"

# Monitor D-Bus BlueZ traffic
ssh deck@${DECK_IP} "dbus-monitor --system \"interface='org.bluez'\""

# Scan for nearby devices
ssh deck@${DECK_IP} "bluetoothctl scan on"

# Check if L2CAP sockets are bound
ssh deck@${DECK_IP} "ss -lnp | grep l2cap"
```

## Common Issues

### Plugin doesn't appear in DeckyLoader

- Verify `plugin.json` exists in `~/homebrew/plugins/deck-controller/`
- Check that `plugin.json` is valid JSON
- Restart DeckyLoader: `sudo systemctl restart plugin_loader`
- Check logs for load errors: `journalctl -u plugin_loader --since "2 min ago"`

### "Permission denied" errors

- Verify `plugin.json` has `"flags": ["root"]`
- Check file permissions: `ls -la ~/homebrew/plugins/deck-controller/main.py`
- Ensure main.py is executable or Python is called correctly by DeckyLoader

### Bluetooth not available

```bash
# Check if bluetoothd is running
systemctl status bluetooth

# Check if adapter exists
hciconfig

# Check if RF kill is blocking
rfkill list bluetooth
rfkill unblock bluetooth
```

### Plugin loads but UI is blank

- Check browser console in Desktop Mode (Ctrl+Shift+I in Steam)
- Verify `dist/index.js` exists and is non-empty
- Check for JavaScript errors in DeckyLoader logs

### Controller input not working

- Check if evdev device exists: `ls /dev/input/event*`
- List input devices: `cat /proc/bus/input/devices | grep -A 5 "Steam\|Xbox\|Valve"`
- Steam Input may have grabbed the controller — try Desktop Mode

## Testing Checklist

- [ ] Plugin loads without errors
- [ ] Status shows "Idle" initially
- [ ] "Start Broadcasting" sets adapter discoverable
- [ ] Target device (phone/PC) discovers "Deck Controller"
- [ ] Pairing completes without PIN prompt
- [ ] Status changes to "Connected"
- [ ] Button presses on Deck register on target device
- [ ] Stick movement is smooth and responsive
- [ ] "Stop Broadcasting" disconnects cleanly
- [ ] Plugin unload restores bluetoothd to original state
- [ ] Settings persist across plugin restart
