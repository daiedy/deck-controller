"""Tests for backend.imu_reader — IMU gyroscope / accelerometer reading.

evdev is mocked via conftest.py's sys.modules setup.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

import evdev
from evdev import ecodes

from backend.imu_reader import (
    CALIBRATION_SAMPLES,
    CalibrationData,
    IMU_DEVICE_NAMES,
    IMUReader,
    MotionState,
)


# ---- MotionState ----


class TestMotionState:
    def test_defaults(self):
        s = MotionState()
        assert s.gyro_x == 0
        assert s.accel_z == 0

    def test_values(self):
        s = MotionState(gyro_x=100, accel_y=-200)
        assert s.gyro_x == 100
        assert s.accel_y == -200


# ---- CalibrationData ----


class TestCalibrationData:
    def test_defaults(self):
        c = CalibrationData()
        assert c.calibrated is False
        assert c.gyro_offset_x == 0

    def test_with_offsets(self):
        c = CalibrationData(gyro_offset_x=10, gyro_offset_y=20, calibrated=True)
        assert c.gyro_offset_x == 10
        assert c.calibrated is True


# ---- IMUReader.find_imu_device ----


class TestFindIMUDevice:
    def test_no_devices(self):
        with patch.object(evdev, "list_devices", return_value=[]):
            assert IMUReader.find_imu_device() is None

    def test_finds_matching_device(self):
        mock_dev = MagicMock()
        mock_dev.name = "Steam Deck Motion Sensors"
        mock_dev.path = "/dev/input/event3"

        with patch.object(evdev, "list_devices", return_value=["/dev/input/event3"]), \
             patch("backend.imu_reader.InputDevice", return_value=mock_dev):
            result = IMUReader.find_imu_device()
            assert result == "/dev/input/event3"

    def test_skips_non_matching(self):
        mock_dev = MagicMock()
        mock_dev.name = "USB Mouse"
        mock_dev.path = "/dev/input/event0"

        with patch.object(evdev, "list_devices", return_value=["/dev/input/event0"]), \
             patch("backend.imu_reader.InputDevice", return_value=mock_dev):
            assert IMUReader.find_imu_device() is None


# ---- IMUReader lifecycle ----


class TestIMUReaderLifecycle:
    def test_initial_state(self):
        reader = IMUReader()
        assert reader.is_running is False
        assert reader.is_calibrated is False

    async def test_start_no_device(self):
        reader = IMUReader()
        with patch.object(IMUReader, "find_imu_device", return_value=None):
            result = await reader.start(callback=lambda s: None)
            assert result is False

    async def test_stop_when_not_running(self):
        reader = IMUReader()
        await reader.stop()  # should not raise
        assert reader.is_running is False


# ---- IMUReader._process_event ----


class TestIMUProcessEvent:
    def _make_reader(self) -> IMUReader:
        reader = IMUReader()
        reader._running = True
        reader._calibration = CalibrationData(calibrated=True)
        reader._callback = MagicMock()
        return reader

    def test_accel_x(self, make_event):
        reader = self._make_reader()
        event = make_event(ecodes.EV_ABS, ecodes.ABS_X, 1000)
        reader._process_event(event)
        assert reader._state.accel_x == 1000

    def test_accel_y(self, make_event):
        reader = self._make_reader()
        event = make_event(ecodes.EV_ABS, ecodes.ABS_Y, -500)
        reader._process_event(event)
        assert reader._state.accel_y == -500

    def test_accel_z(self, make_event):
        reader = self._make_reader()
        event = make_event(ecodes.EV_ABS, ecodes.ABS_Z, 16384)
        reader._process_event(event)
        assert reader._state.accel_z == 16384

    def test_gyro_x_with_calibration(self, make_event):
        reader = self._make_reader()
        reader._calibration.gyro_offset_x = 50
        event = make_event(ecodes.EV_ABS, ecodes.ABS_RX, 150)
        reader._process_event(event)
        assert reader._state.gyro_x == 100  # 150 - 50

    def test_gyro_y_with_calibration(self, make_event):
        reader = self._make_reader()
        reader._calibration.gyro_offset_y = -10
        event = make_event(ecodes.EV_ABS, ecodes.ABS_RY, 20)
        reader._process_event(event)
        assert reader._state.gyro_y == 30  # 20 - (-10)

    def test_gyro_clamped(self, make_event):
        reader = self._make_reader()
        reader._calibration.gyro_offset_x = -50000
        event = make_event(ecodes.EV_ABS, ecodes.ABS_RX, 32767)
        reader._process_event(event)
        assert reader._state.gyro_x == 32767  # clamped

    def test_syn_triggers_callback_when_calibrated(self, make_event):
        reader = self._make_reader()
        event = make_event(ecodes.EV_SYN, 0, 0)
        reader._process_event(event)
        reader._callback.assert_called_once_with(reader._state)

    def test_syn_does_not_callback_during_calibration(self, make_event):
        reader = IMUReader()
        reader._running = True
        reader._callback = MagicMock()
        reader._calibration = CalibrationData(calibrated=False)
        reader._cal_frame_count = 0

        event = make_event(ecodes.EV_SYN, 0, 0)
        reader._process_event(event)
        reader._callback.assert_not_called()
        assert reader._cal_frame_count == 1

    def test_non_abs_event_ignored(self, make_event):
        reader = self._make_reader()
        event = make_event(ecodes.EV_KEY, 0, 1)
        reader._process_event(event)
        # No state change expected
        assert reader._state.accel_x == 0
        reader._callback.assert_not_called()


# ---- Calibration ----


class TestCalibration:
    def test_finalize_calibration(self):
        reader = IMUReader()
        reader._cal_gyro_x = [10, 20, 30]
        reader._cal_gyro_y = [5, 15, 25]
        reader._cal_gyro_z = [-10, -20, -30]

        reader._finalize_calibration()

        assert reader._calibration.calibrated is True
        assert reader._calibration.gyro_offset_x == 20  # (10+20+30)//3
        assert reader._calibration.gyro_offset_y == 15
        assert reader._calibration.gyro_offset_z == -20

    def test_calibration_clears_accumulators(self):
        reader = IMUReader()
        reader._cal_gyro_x = [1, 2, 3]
        reader._cal_gyro_y = [4, 5, 6]
        reader._cal_gyro_z = [7, 8, 9]

        reader._finalize_calibration()

        assert reader._cal_gyro_x == []
        assert reader._cal_gyro_y == []
        assert reader._cal_gyro_z == []

    def test_auto_calibration_after_n_frames(self, make_event):
        reader = IMUReader()
        reader._running = True
        reader._callback = MagicMock()
        reader._calibration = CalibrationData(calibrated=False)
        reader._cal_frame_count = CALIBRATION_SAMPLES - 1
        reader._cal_gyro_x = [10] * 50
        reader._cal_gyro_y = [20] * 50
        reader._cal_gyro_z = [30] * 50

        # This SYN frame should trigger calibration finalization
        syn_event = make_event(ecodes.EV_SYN, 0, 0)
        reader._process_event(syn_event)

        assert reader._calibration.calibrated is True

    def test_gyro_samples_collected_during_calibration(self, make_event):
        reader = IMUReader()
        reader._running = True
        reader._callback = MagicMock()
        reader._calibration = CalibrationData(calibrated=False)

        event = make_event(ecodes.EV_ABS, ecodes.ABS_RX, 42)
        reader._process_event(event)
        assert 42 in reader._cal_gyro_x


# ---- IMUReader async lifecycle (extended) ----


class TestIMUReaderAsyncLifecycleExtended:
    async def test_start_already_running(self):
        reader = IMUReader()
        reader._running = True
        result = await reader.start(callback=lambda s: None)
        assert result is False

    async def test_start_success_and_stop(self):
        reader = IMUReader()
        mock_dev = MagicMock()
        mock_dev.name = "BMI IMU"
        mock_dev.path = "/dev/input/event4"
        mock_dev.close = MagicMock()

        async def _fake_read():
            return
            yield

        mock_dev.async_read_loop = _fake_read

        with patch.object(IMUReader, "find_imu_device", return_value="/dev/input/event4"), \
             patch("backend.imu_reader.InputDevice", return_value=mock_dev):
            result = await reader.start(callback=MagicMock())
            assert result is True
            assert reader.is_running is True

            await reader.stop()
            assert reader.is_running is False
            mock_dev.close.assert_called()

    async def test_start_device_open_failure(self):
        reader = IMUReader()
        with patch.object(IMUReader, "find_imu_device", return_value="/dev/input/event4"), \
             patch("backend.imu_reader.InputDevice", side_effect=OSError("permission denied")):
            result = await reader.start(callback=MagicMock())
            assert result is False

    async def test_read_loop_oserror_stops(self):
        reader = IMUReader()
        mock_dev = MagicMock()
        mock_dev.name = "BMI IMU"
        mock_dev.path = "/dev/input/event4"
        mock_dev.close = MagicMock()

        async def _error_read():
            raise OSError("device gone")
            yield

        mock_dev.async_read_loop = _error_read

        with patch.object(IMUReader, "find_imu_device", return_value="/dev/input/event4"), \
             patch("backend.imu_reader.InputDevice", return_value=mock_dev):
            await reader.start(callback=MagicMock())
            await asyncio.sleep(0.05)
            assert reader._running is False
            await reader.stop()

    def test_find_imu_device_oserror(self):
        with patch.object(evdev, "list_devices", return_value=["/dev/input/event0"]), \
             patch("backend.imu_reader.InputDevice", side_effect=OSError("no access")):
            assert IMUReader.find_imu_device() is None

    def test_gyro_rz_with_calibration(self, make_event):
        """Cover ABS_RZ branch."""
        reader = IMUReader()
        reader._running = True
        reader._calibration = CalibrationData(calibrated=True, gyro_offset_z=5)
        reader._callback = MagicMock()

        event = make_event(ecodes.EV_ABS, ecodes.ABS_RZ, 100)
        reader._process_event(event)
        assert reader._state.gyro_z == 95
