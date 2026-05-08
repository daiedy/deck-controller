"""IMU (gyroscope + accelerometer) reader for Steam Deck."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Optional

try:
    import evdev
    from evdev import InputDevice, ecodes
except ImportError:
    evdev = None  # type: ignore[assignment]

logger = logging.getLogger("deck-controller.imu_reader")

# Steam Deck IMU device name patterns
IMU_DEVICE_NAMES: list[str] = [
    "Steam Deck Motion Sensors",
    "BMI",  # Bosch BMI160/BMI323
    "Valve Software Steam Controller Motion Sensors",
]

# Calibration samples to collect at startup
CALIBRATION_SAMPLES: int = 100


@dataclass
class MotionState:
    """Current IMU state."""

    gyro_x: int = 0
    gyro_y: int = 0
    gyro_z: int = 0
    accel_x: int = 0
    accel_y: int = 0
    accel_z: int = 0


@dataclass
class CalibrationData:
    """Zero-offset calibration for gyroscope."""

    gyro_offset_x: int = 0
    gyro_offset_y: int = 0
    gyro_offset_z: int = 0
    calibrated: bool = False


class IMUReader:
    """Reads IMU (gyroscope + accelerometer) data from Steam Deck.

    The IMU is a separate evdev device from the main controller.
    Includes zero-offset calibration for gyroscope drift.
    """

    def __init__(self) -> None:
        self._device: Optional[InputDevice] = None
        self._running: bool = False
        self._task: Optional[asyncio.Task[None]] = None
        self._state: MotionState = MotionState()
        self._calibration: CalibrationData = CalibrationData()
        self._callback: Optional[Callable[[MotionState], None]] = None
        # Calibration accumulators
        self._cal_gyro_x: list[int] = []
        self._cal_gyro_y: list[int] = []
        self._cal_gyro_z: list[int] = []
        self._cal_frame_count: int = 0

    @staticmethod
    def find_imu_device() -> Optional[str]:
        """Find the IMU evdev device path."""
        if evdev is None:
            return None
        for path in evdev.list_devices():
            try:
                dev = InputDevice(path)
                name_lower = dev.name.lower()
                for pattern in IMU_DEVICE_NAMES:
                    if pattern.lower() in name_lower:
                        dev_path = dev.path
                        dev.close()
                        return dev_path
                dev.close()
            except (OSError, PermissionError):
                continue
        return None

    async def start(self, callback: Callable[[MotionState], None]) -> bool:
        """Start reading IMU data.

        Args:
            callback: Called with updated MotionState on each reading.

        Returns:
            True if started successfully.
        """
        if self._running:
            return False

        if evdev is None:
            logger.error("evdev not available")
            return False

        device_path = self.find_imu_device()
        if device_path is None:
            logger.error("IMU device not found")
            return False

        try:
            self._device = InputDevice(device_path)
            logger.info("Found IMU device: %s at %s", self._device.name, device_path)
        except (OSError, PermissionError) as e:
            logger.error("Cannot open IMU device: %s", e)
            return False

        self._callback = callback
        self._running = True
        self._state = MotionState()
        self._calibration = CalibrationData()
        self._cal_gyro_x = []
        self._cal_gyro_y = []
        self._cal_gyro_z = []
        self._cal_frame_count = 0
        self._task = asyncio.create_task(self._read_loop())
        logger.info("IMU reader started (calibrating...)")
        return True

    async def stop(self) -> None:
        """Stop reading IMU data."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._device is not None:
            try:
                self._device.close()
            except OSError:
                pass
            self._device = None
        logger.info("IMU reader stopped")

    async def _read_loop(self) -> None:
        """Main IMU event reading loop."""
        if self._device is None:
            return

        try:
            async for event in self._device.async_read_loop():
                if not self._running:
                    break
                self._process_event(event)
        except asyncio.CancelledError:
            raise
        except OSError as e:
            logger.error("IMU device read error: %s", e)
            self._running = False

    def _process_event(self, event: object) -> None:
        """Process an IMU evdev event."""
        if evdev is None:
            return

        if event.type == ecodes.EV_SYN:  # type: ignore[union-attr]
            # Frame complete
            if self._calibration.calibrated:
                if self._callback:
                    self._callback(self._state)
            else:
                self._cal_frame_count += 1
                if self._cal_frame_count >= CALIBRATION_SAMPLES:
                    self._finalize_calibration()
            return

        if event.type != ecodes.EV_ABS:  # type: ignore[union-attr]
            return

        code = event.code  # type: ignore[union-attr]
        value = event.value  # type: ignore[union-attr]

        if code == ecodes.ABS_X:
            self._state.accel_x = value
        elif code == ecodes.ABS_Y:
            self._state.accel_y = value
        elif code == ecodes.ABS_Z:
            self._state.accel_z = value
        elif code == ecodes.ABS_RX:
            if not self._calibration.calibrated:
                self._cal_gyro_x.append(value)
            self._state.gyro_x = max(-32768, min(32767, value - self._calibration.gyro_offset_x))
        elif code == ecodes.ABS_RY:
            if not self._calibration.calibrated:
                self._cal_gyro_y.append(value)
            self._state.gyro_y = max(-32768, min(32767, value - self._calibration.gyro_offset_y))
        elif code == ecodes.ABS_RZ:
            if not self._calibration.calibrated:
                self._cal_gyro_z.append(value)
            self._state.gyro_z = max(-32768, min(32767, value - self._calibration.gyro_offset_z))

    def _finalize_calibration(self) -> None:
        """Calculate zero offsets from collected samples."""
        if self._cal_gyro_x:
            self._calibration.gyro_offset_x = sum(self._cal_gyro_x) // len(self._cal_gyro_x)
        if self._cal_gyro_y:
            self._calibration.gyro_offset_y = sum(self._cal_gyro_y) // len(self._cal_gyro_y)
        if self._cal_gyro_z:
            self._calibration.gyro_offset_z = sum(self._cal_gyro_z) // len(self._cal_gyro_z)
        self._calibration.calibrated = True
        self._cal_gyro_x = []
        self._cal_gyro_y = []
        self._cal_gyro_z = []
        logger.info(
            "IMU calibration complete: offsets=(%d, %d, %d)",
            self._calibration.gyro_offset_x,
            self._calibration.gyro_offset_y,
            self._calibration.gyro_offset_z,
        )

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_calibrated(self) -> bool:
        return self._calibration.calibrated
