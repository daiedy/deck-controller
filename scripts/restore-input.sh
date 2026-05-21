#!/usr/bin/env bash
# Restore Steam Deck input controls that were blocked by the plugin.
# Run this BEFORE restarting plugin_loader during deploy so that
# Steam/... buttons and sticks work immediately after restart.
#
# What it does:
#   1. Removes the udev rule that restricts hidraw permissions
#   2. Reloads udev rules
#   3. Rebinds HID-steam driver so hidraw is recreated with normal permissions
#
# Must run as root (sudo).

set -euo pipefail

UDEV_RULE="/run/udev/rules.d/99-deck-controller-block.rules"
HID_UNBIND="/sys/bus/hid/drivers/hid-steam/unbind"
HID_BIND="/sys/bus/hid/drivers/hid-steam/bind"

# Step 1: Remove udev rule if present
if [[ -f "$UDEV_RULE" ]]; then
  rm -f "$UDEV_RULE"
  echo "Removed udev rule"
fi

# Step 2: Reload udev rules
udevadm control --reload-rules 2>/dev/null || true

# Step 3: Find and rebind Valve HID devices (28de:1205)
for dev_path in /sys/bus/hid/drivers/hid-steam/0003:28DE:1205.*; do
  if [[ -e "$dev_path" ]]; then
    hid_id="$(basename "$dev_path")"
    echo "Rebinding HID device: $hid_id"
    echo "$hid_id" > "$HID_UNBIND" 2>/dev/null || true
    sleep 0.1
    echo "$hid_id" > "$HID_BIND" 2>/dev/null || true
    sleep 0.3
  fi
done

echo "Steam Deck input restored"
