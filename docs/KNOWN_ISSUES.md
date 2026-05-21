# Known Issues & Planned Improvements

Tracking items that need further development or investigation.

## 🔴 Not Working

### macOS: No input after pairing

**Status:** Not working
**Platform:** macOS (tested on Mac)

The Steam Deck pairs and connects to macOS via Bluetooth, but no gamepad or mouse input is registered on the Mac side. Likely cause: macOS has stricter HID protocol requirements than Android. The `GET_REPORT` handler was fixed (correct Report ID routing + DATA header), but the issue persists — further investigation needed.

**Possible areas to investigate:**
- macOS may require boot protocol support (`HIDBootDevice = true` in SDP + boot-mode report handling)
- IOKit HID driver on macOS may reject composite descriptors with vendor-specific reports (Report ID 0x03 motion sensor)
- macOS may need specific HID handshake ordering or additional control channel messages
- Connection interval / sniff mode parameters may differ from what macOS expects

---

## 🟡 Needs Improvement

### Android: Trackpad cursor movement is choppy

**Status:** Works, but with noticeable lag compared to a real BT mouse
**Platform:** Android

Drawing circles or making rapid trackpad movements produces jerky/stuttery cursor motion. Slow deliberate movements are acceptable, but fast movements lag behind noticeably.

**Root cause analysis:**
- Steam Deck trackpad hardware polls at 250 Hz (4ms interval)
- Data path: trackpad → USB → kernel → hidraw → Python → struct unpack → delta calc → BT L2CAP — each hop adds latency
- Real BT mice have sensor → MCU → BT radio in a single chip (<1ms total)
- Python GIL and asyncio overhead add ~1-2ms per frame
- BT Classic connection interval is ~11ms (host-controlled, not negotiable from our side)
- Total minimum latency: ~13-15ms vs ~1-3ms for a dedicated BT mouse

**Optimizations already applied:**
- Direct `os.write()` from input reader thread (bypasses sender thread)
- `select()` timeout reduced to 4ms (matches hardware poll rate)
- Drop-on-buffer-full instead of accumulation (prevents lag buildup)
- Linear 1/256 scaling (predictable, no acceleration artifacts)

**Possible further improvements:**
- Rewrite critical path in C extension (eliminate Python overhead)
- Use raw HID (bypass evdev) to shave ~1ms off input read
- Investigate BLE HID instead of BT Classic (configurable connection interval)
