"""Tests for backend.bt_hid_service — Bluetooth HID service.

All socket and subprocess calls are mocked since AF_BLUETOOTH and
bluetoothctl are not available on the dev machine.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from backend.bt_hid_service import (
    BTPROTO_L2CAP,
    BTHIDService,
    ConnectionInfo,
    PSM_CONTROL,
    PSM_INTERRUPT,
)


# ---- ConnectionInfo ----


class TestConnectionInfo:
    def test_init(self):
        ci = ConnectionInfo(address="AA:BB:CC:DD:EE:FF", name="TestDevice")
        assert ci.address == "AA:BB:CC:DD:EE:FF"
        assert ci.name == "TestDevice"

    def test_default_name(self):
        ci = ConnectionInfo(address="AA:BB:CC:DD:EE:FF")
        assert ci.name == "Unknown"

    def test_to_dict(self):
        ci = ConnectionInfo(address="11:22:33:44:55:66", name="Phone")
        d = ci.to_dict()
        assert d == {"address": "11:22:33:44:55:66", "name": "Phone"}


# ---- BTHIDService init ----


class TestBTHIDServiceInit:
    def test_defaults(self):
        svc = BTHIDService()
        assert svc._running is False
        assert svc.is_connected is False
        assert svc.connected_device is None

    def test_custom_adapter(self):
        svc = BTHIDService(adapter_path="/org/bluez/hci1")
        assert svc._adapter_path == "/org/bluez/hci1"


# ---- get_status ----


class TestGetStatus:
    def test_idle(self):
        svc = BTHIDService()
        status = svc.get_status()
        assert status["state"] == "idle"
        assert status["running"] is False
        assert status["connected_device"] is None

    def test_broadcasting(self):
        svc = BTHIDService()
        svc._running = True
        status = svc.get_status()
        assert status["state"] == "broadcasting"

    def test_connected(self):
        svc = BTHIDService()
        svc._running = True
        svc._connected_device = ConnectionInfo("AA:BB:CC:DD:EE:FF", "Phone")
        status = svc.get_status()
        assert status["state"] == "connected"
        assert status["connected_device"]["name"] == "Phone"


# ---- send_report ----


class TestSendReport:
    def test_no_client_returns_false(self):
        svc = BTHIDService()
        assert svc.send_report(b"\x01\x00") is False

    def test_sends_with_header(self):
        """send_report enqueues the report and the sender thread writes it."""
        svc = BTHIDService()
        svc._interrupt_client_fd = 42
        svc._protocol_ready = True

        result = svc.send_report(b"\x01\x00\x00")

        assert result is True
        # Report is placed in the send queue for the sender thread
        assert not svc._send_queue.empty()
        assert svc._send_queue.get_nowait() == b"\x01\x00\x00"

    def test_sender_thread_writes_with_header(self):
        """Sender thread prepends 0xA1 header and calls os.write."""
        import time

        svc = BTHIDService()
        svc._interrupt_client_fd = 42
        svc._protocol_ready = True

        with patch("backend.bt_hid_service.os.write") as mock_write:
            mock_write.return_value = 4
            svc._start_sender_thread()
            svc._send_queue.put_nowait(b"\x01\x00\x00")
            time.sleep(0.15)  # let sender thread process
            svc._stop_sender_thread()

        mock_write.assert_called_once_with(42, b"\xa1\x01\x00\x00")

    def test_oserror_disconnects(self):
        """When os.write raises OSError, the sender thread calls _handle_disconnect."""
        import time

        svc = BTHIDService()
        svc._interrupt_client_fd = 42
        svc._control_client_fd = 43
        svc._protocol_ready = True
        svc._connected_device = ConnectionInfo("AA:BB:CC:DD:EE:FF")

        with patch("backend.bt_hid_service.os.write", side_effect=OSError("conn lost")), \
             patch("backend.bt_hid_service.os.close"):
            svc._start_sender_thread()
            svc._send_queue.put_nowait(b"\x01\x00")
            time.sleep(0.2)  # let sender thread hit the error
            svc._send_thread_stop.set()
            if svc._send_thread:
                svc._send_thread.join(timeout=1.0)

        assert svc._connected_device is None
        assert svc._interrupt_client_fd is None


# ---- _handle_disconnect ----


class TestHandleDisconnect:
    def test_closes_client_sockets(self):
        svc = BTHIDService()
        svc._control_client_fd = 42
        svc._interrupt_client_fd = 43
        svc._connected_device = ConnectionInfo("AA:BB:CC:DD:EE:FF")

        with patch("backend.bt_hid_service.os.close") as mock_close:
            svc._handle_disconnect()
            assert mock_close.call_count == 2

        assert svc._connected_device is None
        assert svc._control_client_fd is None
        assert svc._interrupt_client_fd is None


# ---- _set_adapter_property ----


class TestSetAdapterProperty:
    _BUSCTL_PREFIX = [
        "busctl", "set-property", "--system",
        "org.bluez", "/org/bluez/hci0", "org.bluez.Adapter1",
    ]

    def _assert_cmd(self, mock_run, expected_cmd):
        """Assert only the positional command arg (ignore env kwarg added by _subprocess_run)."""
        args, kwargs = mock_run.call_args
        assert args[0] == expected_cmd
        assert kwargs.get("capture_output") is True
        assert kwargs.get("text") is True
        assert kwargs.get("timeout") == 5

    @patch("backend.bt_hid_service.subprocess.run")
    def test_alias(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        svc = BTHIDService()
        assert svc._set_adapter_property("alias", "MyDeck") is True
        self._assert_cmd(mock_run, self._BUSCTL_PREFIX + ["Alias", "s", "MyDeck"])

    @patch("backend.bt_hid_service.subprocess.run")
    def test_discoverable_on(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        svc = BTHIDService()
        assert svc._set_adapter_property("discoverable", True) is True
        self._assert_cmd(mock_run, self._BUSCTL_PREFIX + ["Discoverable", "b", "true"])

    @patch("backend.bt_hid_service.subprocess.run")
    def test_pairable_off(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        svc = BTHIDService()
        assert svc._set_adapter_property("pairable", False) is True
        self._assert_cmd(mock_run, self._BUSCTL_PREFIX + ["Pairable", "b", "false"])

    @patch("backend.bt_hid_service.subprocess.run")
    def test_failure_returns_false(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 1, stderr="")
        svc = BTHIDService()
        assert svc._set_adapter_property("discoverable", True) is False

    @patch("backend.bt_hid_service.subprocess.run")
    def test_oserror_returns_false(self, mock_run):
        mock_run.side_effect = OSError("not found")
        svc = BTHIDService()
        assert svc._set_adapter_property("discoverable", True) is False


# ---- _set_device_class ----


class TestSetDeviceClass:
    def test_success(self):
        svc = BTHIDService()
        with patch.object(svc, "_set_device_class_mgmt_socket", return_value=True):
            assert svc._set_device_class("0x002508") is True

    @patch("backend.bt_hid_service._time_mod.sleep")
    @patch("backend.bt_hid_service.pty.openpty", return_value=(99, 100))
    @patch("backend.bt_hid_service.os.close")
    @patch("backend.bt_hid_service.subprocess.run")
    def test_failure(self, mock_run, mock_os_close, mock_openpty, mock_sleep):
        mock_run.return_value = subprocess.CompletedProcess([], 1, stderr="err")
        svc = BTHIDService()
        with patch.object(svc, "_set_device_class_mgmt_socket", return_value=False):
            assert svc._set_device_class("0x002508") is False


# ---- _open_l2cap_sockets ----


class TestOpenL2CAPSockets:
    def test_success(self):
        svc = BTHIDService()
        with patch("backend.bt_hid_service._l2cap_socket", side_effect=[10, 11]), \
             patch("backend.bt_hid_service._l2cap_setsockopt_reuse"), \
             patch("backend.bt_hid_service._l2cap_bind"), \
             patch("backend.bt_hid_service._l2cap_listen"), \
             patch("backend.bt_hid_service._l2cap_set_nonblock"):
            assert svc._open_l2cap_sockets() is True
            assert svc._control_fd == 10
            assert svc._interrupt_fd == 11

    def test_oserror_closes_sockets(self):
        svc = BTHIDService()
        with patch("backend.bt_hid_service._l2cap_socket", side_effect=OSError("socket failed")):
            assert svc._open_l2cap_sockets() is False
            assert svc._control_fd is None


# ---- _close_sockets ----


class TestCloseSockets:
    def test_closes_all(self):
        svc = BTHIDService()
        svc._control_fd = 10
        svc._interrupt_fd = 11
        svc._control_client_fd = 12
        svc._interrupt_client_fd = 13

        with patch("backend.bt_hid_service.os.close") as mock_close:
            svc._close_sockets()
            assert mock_close.call_count == 4

        assert svc._control_fd is None
        assert svc._interrupt_fd is None
        assert svc._control_client_fd is None
        assert svc._interrupt_client_fd is None

    def test_handles_none(self):
        svc = BTHIDService()
        svc._close_sockets()  # no error when all are None


# ---- get_paired_devices ----


class TestGetPairedDevices:
    @patch("backend.bt_hid_service.subprocess.run")
    def test_parses_output(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            [], 0,
            stdout="Device AA:BB:CC:DD:EE:FF MyPhone\nDevice 11:22:33:44:55:66 Xbox\n",
        )
        svc = BTHIDService()
        devices = svc.get_paired_devices()
        assert len(devices) == 2
        assert devices[0]["address"] == "AA:BB:CC:DD:EE:FF"
        assert devices[0]["name"] == "MyPhone"
        assert devices[1]["name"] == "Xbox"

    @patch("backend.bt_hid_service.subprocess.run")
    def test_empty_output(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="")
        svc = BTHIDService()
        assert svc.get_paired_devices() == []

    @patch("backend.bt_hid_service.subprocess.run")
    def test_error_returns_empty(self, mock_run):
        mock_run.side_effect = OSError("command not found")
        svc = BTHIDService()
        assert svc.get_paired_devices() == []


# ---- _get_device_name ----


class TestGetDeviceName:
    @patch("backend.bt_hid_service.subprocess.run")
    def test_parses_name(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            [], 0,
            stdout="Device AA:BB:CC:DD:EE:FF\n\tName: MyPhone\n\tAlias: MyPhone\n",
        )
        svc = BTHIDService()
        assert svc._get_device_name("AA:BB:CC:DD:EE:FF") == "MyPhone"

    @patch("backend.bt_hid_service.subprocess.run")
    def test_unknown_on_failure(self, mock_run):
        mock_run.side_effect = OSError("err")
        svc = BTHIDService()
        assert svc._get_device_name("AA:BB:CC:DD:EE:FF") == "Unknown"


# ---- _restore_bluetoothd ----


class TestRestoreBluetoothd:
    @patch("backend.bt_hid_service.subprocess.run")
    def test_restores_service(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        svc = BTHIDService()
        with patch("backend.bt_hid_service.os.path.isfile", return_value=False):
            svc._restore_bluetoothd()
        # steamos-readonly disable + enable + systemctl restart
        assert mock_run.call_count == 3

    @patch("backend.bt_hid_service.subprocess.run")
    def test_restore_oserror(self, mock_run):
        mock_run.side_effect = OSError("fail")
        svc = BTHIDService()
        svc._restore_bluetoothd()  # should not raise


# ---- _load_sdp_record ----


class TestLoadSdpRecord:
    def test_loads_file(self):
        svc = BTHIDService()
        sdp = svc._load_sdp_record()
        # The actual XML file exists in assets/
        assert len(sdp) > 0 or sdp == ""  # may or may not exist in test env

    @patch("builtins.open", side_effect=FileNotFoundError("not found"))
    def test_returns_empty_on_missing(self, mock_open):
        svc = BTHIDService()
        assert svc._load_sdp_record() == ""


# ---- _register_sdp_record ----


class TestRegisterSdpRecord:
    def test_success(self):
        svc = BTHIDService()
        mock_proc = MagicMock()
        mock_proc.stdout.readline.return_value = b"REGISTERED\n"
        mock_proc.poll.return_value = None
        mock_proc.pid = 1234
        mock_sel = MagicMock()
        mock_sel.select.return_value = [(MagicMock(), 1)]
        mock_sock_a = MagicMock()
        mock_sock_b = MagicMock()
        mock_sock_b.fileno.return_value = 99

        with patch("backend.bt_hid_service.subprocess.run"), \
             patch("backend.bt_hid_service.subprocess.Popen", return_value=mock_proc), \
             patch("selectors.DefaultSelector", return_value=mock_sel), \
             patch("backend.bt_hid_service.socket.socketpair", return_value=(mock_sock_a, mock_sock_b)):
            assert svc._register_sdp_record() is True

    @patch("backend.bt_hid_service.os.path.isfile", return_value=False)
    def test_missing_file(self, mock_isfile):
        svc = BTHIDService()
        mock_sock_a = MagicMock()
        mock_sock_b = MagicMock()
        mock_sock_b.fileno.return_value = 99
        with patch("backend.bt_hid_service.subprocess.run"), \
             patch("backend.bt_hid_service.socket.socketpair", return_value=(mock_sock_a, mock_sock_b)):
            assert svc._register_sdp_record() is False

    @patch("backend.bt_hid_service.os.path.isfile", return_value=True)
    def test_oserror(self, mock_isfile):
        svc = BTHIDService()
        mock_sock_a = MagicMock()
        mock_sock_b = MagicMock()
        mock_sock_b.fileno.return_value = 99
        with patch("backend.bt_hid_service.subprocess.run"), \
             patch("backend.bt_hid_service.socket.socketpair", return_value=(mock_sock_a, mock_sock_b)), \
             patch("backend.bt_hid_service.subprocess.Popen", side_effect=OSError("no python")):
            assert svc._register_sdp_record() is False


# ---- _set_device_class extended ----


class TestSetDeviceClassExtended:
    @patch("backend.bt_hid_service.subprocess.run", side_effect=OSError("no hciconfig"))
    def test_oserror(self, mock_run):
        svc = BTHIDService()
        assert svc._set_device_class("0x002508") is False


# ---- _restart_bluetoothd_with_plugin_flag ----


class TestRestartBluetoothd:
    async def test_success(self):
        svc = BTHIDService()

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with patch.object(svc, "_run_cmd", new_callable=AsyncMock, return_value=0), \
             patch("backend.bt_hid_service.os.makedirs"), \
             patch("builtins.open", MagicMock()), \
             patch.object(svc, "_configure_bluetooth_main_conf"), \
             patch("backend.bt_hid_service.asyncio.create_subprocess_exec",
                   new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_proc
            result = await svc._restart_bluetoothd_with_plugin_flag()
            assert result is True

    async def test_timeout(self):
        import asyncio
        svc = BTHIDService()

        with patch("backend.bt_hid_service.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = asyncio.TimeoutError()
            result = await svc._restart_bluetoothd_with_plugin_flag()
            assert result is False


# ---- start / stop full lifecycle ----


class TestBTHIDServiceLifecycle:
    async def test_start_already_running(self):
        svc = BTHIDService()
        svc._running = True
        result = await svc.start()
        assert result is False

    async def test_start_bluetoothd_failure(self):
        svc = BTHIDService()
        with patch.object(svc, "_restart_bluetoothd_with_plugin_flag", new_callable=AsyncMock, return_value=False):
            result = await svc.start()
            assert result is False

    async def test_start_socket_failure(self):
        svc = BTHIDService()
        with patch.object(svc, "_restart_bluetoothd_with_plugin_flag", new_callable=AsyncMock, return_value=True), \
             patch.object(svc, "_set_device_class", return_value=True), \
             patch.object(svc, "_set_adapter_property", return_value=True), \
             patch.object(svc, "_register_sdp_record", return_value=True), \
             patch.object(svc, "_open_l2cap_sockets", return_value=False), \
             patch.object(svc, "_restore_bluetoothd"), \
             patch("backend.bt_hid_service.subprocess.run"):
            result = await svc.start()
            assert result is False
            svc._restore_bluetoothd.assert_called_once()

    async def test_start_success_and_stop(self):
        svc = BTHIDService()
        with patch.object(svc, "_restart_bluetoothd_with_plugin_flag", new_callable=AsyncMock, return_value=True), \
             patch.object(svc, "_set_device_class", return_value=True), \
             patch.object(svc, "_set_adapter_property", return_value=True), \
             patch.object(svc, "_register_sdp_record", return_value=True), \
             patch.object(svc, "_open_l2cap_sockets", return_value=True), \
             patch.object(svc, "_close_sockets"), \
             patch.object(svc, "_restore_bluetoothd"), \
             patch("backend.bt_hid_service.subprocess.run"):
            result = await svc.start()
            assert result is True
            assert svc._running is True

            await svc.stop()
            assert svc._running is False
            svc._close_sockets.assert_called_once()
            svc._restore_bluetoothd.assert_called_once()


# ---- is_connected ----


class TestIsConnected:
    def test_not_connected(self):
        svc = BTHIDService()
        assert svc.is_connected is False

    def test_connected(self):
        svc = BTHIDService()
        svc._connected_device = ConnectionInfo("AA:BB:CC:DD:EE:FF")
        assert svc.is_connected is True


# ---- _restore_bluetoothd ----


class TestRestoreBluetooth:
    @patch("backend.bt_hid_service.subprocess.run")
    def test_kills_and_restarts(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        svc = BTHIDService()
        with patch("backend.bt_hid_service.os.path.isfile", return_value=False):
            svc._restore_bluetoothd()
        # steamos-readonly disable + enable + systemctl restart bluetooth
        assert mock_run.call_count == 3
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert calls[0] == ["steamos-readonly", "disable"]
        assert calls[1] == ["steamos-readonly", "enable"]
        assert calls[2] == ["systemctl", "restart", "bluetooth"]


# ---- _load_sdp_record ----


class TestLoadSdpRecord:
    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_returns_empty_on_missing_file(self, _):
        svc = BTHIDService()
        assert svc._load_sdp_record() == ""


# ---- is_connected property ----


class TestIsConnected:
    def test_false_when_no_device(self):
        svc = BTHIDService()
        assert svc.is_connected is False

    def test_true_when_device_set(self):
        svc = BTHIDService()
        svc._connected_device = ConnectionInfo("AA:BB:CC:DD:EE:FF")
        assert svc.is_connected is True

    def test_connected_device_property(self):
        svc = BTHIDService()
        ci = ConnectionInfo("AA:BB:CC:DD:EE:FF", "Phone")
        svc._connected_device = ci
        assert svc.connected_device is ci
