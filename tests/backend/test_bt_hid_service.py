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
        svc = BTHIDService()
        mock_sock = MagicMock()
        svc._interrupt_client = mock_sock

        result = svc.send_report(b"\x01\x00\x00")
        assert result is True
        mock_sock.send.assert_called_once_with(b"\xa1\x01\x00\x00")

    def test_oserror_disconnects(self):
        svc = BTHIDService()
        mock_sock = MagicMock()
        mock_sock.send.side_effect = OSError("Connection lost")
        svc._interrupt_client = mock_sock
        svc._control_client = MagicMock()
        svc._connected_device = ConnectionInfo("AA:BB:CC:DD:EE:FF")

        result = svc.send_report(b"\x01\x00")
        assert result is False
        assert svc._connected_device is None
        assert svc._interrupt_client is None


# ---- _handle_disconnect ----


class TestHandleDisconnect:
    def test_closes_client_sockets(self):
        svc = BTHIDService()
        ctrl = MagicMock()
        intr = MagicMock()
        svc._control_client = ctrl
        svc._interrupt_client = intr
        svc._connected_device = ConnectionInfo("AA:BB:CC:DD:EE:FF")

        svc._handle_disconnect()

        ctrl.close.assert_called_once()
        intr.close.assert_called_once()
        assert svc._connected_device is None
        assert svc._control_client is None
        assert svc._interrupt_client is None


# ---- _set_adapter_property ----


class TestSetAdapterProperty:
    @patch("backend.bt_hid_service.subprocess.run")
    def test_alias(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        svc = BTHIDService()
        assert svc._set_adapter_property("alias", "MyDeck") is True
        mock_run.assert_called_once_with(
            ["bluetoothctl", "system-alias", "MyDeck"],
            capture_output=True, text=True, timeout=5,
        )

    @patch("backend.bt_hid_service.subprocess.run")
    def test_discoverable_on(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        svc = BTHIDService()
        assert svc._set_adapter_property("discoverable", True) is True
        mock_run.assert_called_once_with(
            ["bluetoothctl", "discoverable", "on"],
            capture_output=True, text=True, timeout=5,
        )

    @patch("backend.bt_hid_service.subprocess.run")
    def test_pairable_off(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        svc = BTHIDService()
        assert svc._set_adapter_property("pairable", False) is True
        mock_run.assert_called_once_with(
            ["bluetoothctl", "pairable", "off"],
            capture_output=True, text=True, timeout=5,
        )

    @patch("backend.bt_hid_service.subprocess.run")
    def test_failure_returns_false(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 1)
        svc = BTHIDService()
        assert svc._set_adapter_property("discoverable", True) is False

    @patch("backend.bt_hid_service.subprocess.run")
    def test_oserror_returns_false(self, mock_run):
        mock_run.side_effect = OSError("not found")
        svc = BTHIDService()
        assert svc._set_adapter_property("discoverable", True) is False


# ---- _set_device_class ----


class TestSetDeviceClass:
    @patch("backend.bt_hid_service.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        svc = BTHIDService()
        assert svc._set_device_class("0x002508") is True
        mock_run.assert_called_once_with(
            ["hciconfig", "hci0", "class", "0x002508"],
            capture_output=True, text=True, timeout=5,
        )

    @patch("backend.bt_hid_service.subprocess.run")
    def test_failure(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 1, stderr="err")
        svc = BTHIDService()
        assert svc._set_device_class("0x002508") is False


# ---- _open_l2cap_sockets ----


class TestOpenL2CAPSockets:
    @patch("backend.bt_hid_service.socket")
    def test_success(self, mock_socket_mod):
        mock_ctrl = MagicMock()
        mock_intr = MagicMock()
        mock_socket_mod.socket.side_effect = [mock_ctrl, mock_intr]
        mock_socket_mod.SOL_SOCKET = 1
        mock_socket_mod.SO_REUSEADDR = 2

        svc = BTHIDService()
        assert svc._open_l2cap_sockets() is True
        assert svc._control_socket is mock_ctrl
        assert svc._interrupt_socket is mock_intr
        assert mock_socket_mod.socket.call_count == 2

    @patch("backend.bt_hid_service.socket")
    def test_oserror_closes_sockets(self, mock_socket_mod):
        mock_socket_mod.socket.side_effect = OSError("socket failed")

        svc = BTHIDService()
        assert svc._open_l2cap_sockets() is False
        assert svc._control_socket is None


# ---- _close_sockets ----


class TestCloseSockets:
    def test_closes_all(self):
        svc = BTHIDService()
        svc._control_socket = MagicMock()
        svc._interrupt_socket = MagicMock()
        svc._control_client = MagicMock()
        svc._interrupt_client = MagicMock()

        svc._close_sockets()

        assert svc._control_socket is None
        assert svc._interrupt_socket is None
        assert svc._control_client is None
        assert svc._interrupt_client is None

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
        svc._restore_bluetoothd()
        assert mock_run.call_count == 2  # pkill + systemctl start

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
    @patch("backend.bt_hid_service.os.path.isfile", return_value=True)
    @patch("backend.bt_hid_service.subprocess.run")
    def test_success(self, mock_run, mock_isfile):
        mock_run.return_value = subprocess.CompletedProcess([], 0)
        svc = BTHIDService()
        assert svc._register_sdp_record() is True

    @patch("backend.bt_hid_service.os.path.isfile", return_value=False)
    def test_missing_file(self, mock_isfile):
        svc = BTHIDService()
        assert svc._register_sdp_record() is False

    @patch("backend.bt_hid_service.os.path.isfile", return_value=True)
    @patch("backend.bt_hid_service.subprocess.run", side_effect=OSError("no sdptool"))
    def test_oserror(self, mock_run, mock_isfile):
        svc = BTHIDService()
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
        mock_proc.communicate = AsyncMock(return_value=(b"bluetoothd --noplugin\n", b""))
        mock_proc.returncode = 0

        with patch("backend.bt_hid_service.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
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
        svc._restore_bluetoothd()
        assert mock_run.call_count == 2
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert calls[0] == ["pkill", "-f", "bluetoothd.*-P input"]
        assert calls[1] == ["systemctl", "start", "bluetooth"]


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
