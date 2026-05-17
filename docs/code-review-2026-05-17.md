# Code Review: deck-controller

Commit range: a553b66..e08545e (HEAD: e08545eb17d6e267f3827a7fdb438249331a4c9c)
Date: 2026-05-17T17:38:27+04:00

Summary
-------
This review inspects recent changes (Python backend + React frontend) focusing on security, resource cleanup, asyncio patterns, and alignment with documented architecture. The report lists issues found, their severity, and recommended fixes. No code changes are made here.

Findings
-------

1) backend/bt_hid_service.py: L2CAP sockaddr packing & libc usage
- Location: backend/bt_hid_service.py lines ~57-116, 74-88, 104-116
- Severity: 🟡 warning
- Description: The code bypasses Python socket helpers and builds sockaddr_l2 with struct.pack("<HH6sHB", ...). This assumes a specific struct layout and endianness. While necessary in this sandbox, the hard-coded AF_BLUETOOTH/struct layout may be brittle across kernels/distributions or future Python builds.
- Recommended fix: Add defensive checks and feature-detection (e.g., verify runtime sizeof sockaddr_l2 via ctypes, or fallback to documented syscall packing). Encapsulate packing into a helper with unit tests and clear comment referencing kernel struct definitions. Add runtime sanity-checks (e.g., bind -> getsockname -> verify PSM).

2) backend/bt_hid_service.py: async accept/connect thread polling
- Location: backend/bt_hid_service.py lines ~119-134, 154-196
- Severity: 🔵 suggestion
- Description: _l2cap_async_accept and _l2cap_async_connect use run_in_executor with select-based polling. This is acceptable given sandbox constraints, but busy-wait/select loops could delay shutdown.
- Recommended fix: Ensure threads/executor tasks are cancellable and add shorter select timeouts or an explicit shutdown event. Document why add_reader/add_writer is unavailable (PyInstaller sandbox) so future maintainers understand the trade-off.

3) backend/bt_hid_service.py: bluetoothd restart and steamos-readonly handling
- Location: backend/bt_hid_service.py lines ~327-371, 404-448
- Severity: 🟡 warning
- Description: The code disables read-only, writes systemd override, then re-enables. Multiple subprocess calls and file operations occur; if an unexpected exception occurs between disable/enable, system state could be left in read-only-disabled state or override file partially written.
- Recommended fix: Surround disabling/enabling with robust try/finally that guarantees re-enabling steamos-readonly and restores previous state on all error paths. Add logging that records when the system readonly flag was changed and a diagnostic hook to detect inconsistent state.

4) backend/bt_hid_service.py: SDP helper lifecycle
- Location: backend/bt_hid_service.py lines ~744-816, 807-818
- Severity: 🟡 warning
- Description: The persistent SDP helper is spawned as a subprocess and parsed for a "REGISTERED" line. If the helper dies or prints unexpected content, code kills it. However, in certain SIGKILL scenarios a stale helper may remain; _kill_stale_helpers tries to pkill by pattern, which may be broad.
- Recommended fix: When spawning the helper, record the PID to a pidfile under plugin runtime dir and prefer targeted termination of that PID during cleanup. Avoid broad pkill -f matches where possible.

5) backend/bt_hid_service.py: send_report protocol readiness
- Location: backend/bt_hid_service.py lines ~1431-1464
- Severity: 🔵 suggestion
- Description: send_report silently returns False if _protocol_ready is false or no interrupt fd; callers may ignore failures. This is correct, but losing early reports without logging may hide issues.
- Recommended fix: Consider optional diagnostic logging on first N suppressed reports per connection, or have send_report return an error result that callers can surface via RPC logs.

6) backend/input_reader.py: HID driver rebind and udev rule manipulation
- Location: backend/input_reader.py lines ~639-709, 716-776, 778-796
- Severity: 🟡 warning
- Description: The plugin writes a udev rule to /run/udev/rules.d and rebinding via sysfs to block Steam. These operations require root and interact with platform device state; failures could leave controller inaccessible.
- Recommended fix: Ensure _cleanup_udev_rule is always invoked on any failure path (it is called in places, good), add more descriptive logging on each step, and consider a transactional approach (write to a temp file then atomically rename).

7) backend/input_reader.py: threaded read loop & device swap handling
- Location: backend/input_reader.py lines ~824-924, 865-886
- Severity: 🔵 suggestion
- Description: The read loop uses background threads to bridge blocking reads to asyncio queues. This is appropriate, but joining threads on shutdown relies on timely thread termination. Unexpected blocking reads may delay plugin unload.
- Recommended fix: Add explicit thread stop notifications (Event) and ensure reader threads use small BlockingIO waits; already mostly present but add timeouts and watchdog to avoid long joins.

8) frontend (React): console.error usage in production code
- Location: src/hooks/useBackend.ts lines ~71-93 and ~140-152; src/index.tsx lines ~14-19
- Severity: 🔵 suggestion
- Description: The frontend uses console.error for runtime errors and in hook catch blocks. Project already exposes a log_frontend_error RPC; using console.* may not be visible in DeckyLoader logs.
- Recommended fix: Replace console.error calls with the callable log_frontend_error or surface errors in the UI (setLastError). Keep console logging only for local dev; gate with a debug flag.

9) frontend (React): error reporting sanitation
- Location: src/index.tsx lines ~13-19 and main.tsx error boundary
- Severity: 🟡 warning
- Description: log_frontend_error writes untrusted strings (error, stack, url, component) into a file under plugin settings. These strings are not sanitized and could include newlines or control characters.
- Recommended fix: Sanitize or escape newline/control characters when writing logs. Limit per-entry size and consider JSON-lines format for easier parsing.

10) General: tests and CI changes
- Location: repository tests and vitest.config.ts
- Severity: 🔵 suggestion
- Description: GitHub Actions removed in recent commits; local verification added. Ensure repository contributors know how to run local verification and that test runners replicate CI environment (node version, python deps).
- Recommended fix: Add a CONTRIBUTING.md section describing local verification steps (commands and expected environment), or provide a small script to run tests in CI-equivalent manner.

Architecture / Plan Alignment
---------------------------
- docs/ARCHITECTURE.md describes the BlueZ/evdev/L2CAP architecture that the code implements; the recent changes (composite HID, driver rebinding) align with the architecture. No major architecture drift observed.
- There is no .planning/ROADMAP.md present in the repository root — no roadmap file to compare. If roadmap exists elsewhere, please supply path.

Action items (recommended prioritization)
---------------------------------------
1. Sanitize frontend error logging and replace console.error with log_frontend_error (low-risk, quick win).
2. Harden bluetoothd restart and steamos-readonly interactions with stronger try/finally to guarantee restoration (high priority: system state risk).
3. Replace broad pkill -f for SDP helper with PID-based cleanup (medium priority).
4. Add runtime checks and defensive comments around L2CAP sockaddr packing (medium priority).
5. Add unit tests for L2CAP helper packing and socket error paths (low priority).

Appendix: quick notes for maintainers
------------------------------------
- All cleanup paths appear implemented: main._unload() calls input_reader.stop(), imu_reader.stop(), and bt_service.stop(); BTHIDService.stop attempts to restore bluetoothd and kill helpers. Verify plugin unload under SIGKILL does not leave persistent artifacts — some helper pkill logic exists.
- BlueZ interactions are fragile inside PyInstaller sandbox; the code documents and works around several limitations (lack of add_reader, btmgmt stdin problems) — keep these notes when refactoring.
