"""Background CPU/GPU polling.

Runs on a QThread so psutil/pynvml calls never block the GUI thread, and
polls infrequently (every ``poll_interval_seconds``, default 2s) rather
than every animation frame, per the performance requirements. Emits a
plain ``SystemSample`` - it never touches the pet window or animation
directly, keeping the "system monitor must not manipulate the GUI"
architectural rule.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

import psutil
from PySide6.QtCore import QThread, Signal

from . import utils

logger = utils.get_logger("system_monitor")

try:
    import pynvml

    _NVML_IMPORT_OK = True
except ImportError:
    pynvml = None  # type: ignore[assignment]
    _NVML_IMPORT_OK = False


class Severity(Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


@dataclass
class SystemSample:
    cpu_percent: float
    gpu_percent: float | None  # None means unavailable
    severity: Severity


class _NvmlGpuReader:
    """Thin wrapper around pynvml that degrades to "unavailable" cleanly."""

    def __init__(self) -> None:
        self.available = False
        self._handle = None
        if not _NVML_IMPORT_OK:
            logger.info("pynvml not installed; GPU monitoring disabled")
            return
        try:
            pynvml.nvmlInit()
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self.available = True
        except Exception as exc:  # noqa: BLE001 - any NVML failure just disables GPU monitoring
            logger.info("NVML unavailable (%s); GPU monitoring disabled", exc)
            self.available = False

    def read_percent(self) -> float | None:
        if not self.available or self._handle is None:
            return None
        try:
            util = pynvml.nvmlDeviceGetUtilizationRates(self._handle)
            return float(util.gpu)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to read GPU utilization; disabling GPU monitoring")
            self.available = False
            return None

    def shutdown(self) -> None:
        if _NVML_IMPORT_OK and self.available:
            try:
                pynvml.nvmlShutdown()
            except Exception:  # noqa: BLE001
                pass


class SystemMonitor(QThread):
    """Polls CPU (and GPU, if available) on an interval and emits samples."""

    sample_ready = Signal(object)  # SystemSample

    def __init__(
        self,
        poll_interval_seconds: float = 2.0,
        monitor_cpu: bool = True,
        monitor_gpu: bool = True,
        yellow_threshold: float = 50.0,
        red_threshold: float = 80.0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.poll_interval_seconds = poll_interval_seconds
        self.monitor_cpu = monitor_cpu
        self.monitor_gpu = monitor_gpu
        self.yellow_threshold = yellow_threshold
        self.red_threshold = red_threshold
        self._running = False
        self._gpu_reader: _NvmlGpuReader | None = None
        self._cpu_history: list[float] = []

    def update_thresholds(self, yellow: float, red: float) -> None:
        self.yellow_threshold = yellow
        self.red_threshold = red

    def _severity_for(self, cpu: float, gpu: float | None) -> Severity:
        worst = max(cpu, gpu or 0.0)
        if worst >= self.red_threshold:
            return Severity.RED
        if worst >= self.yellow_threshold:
            return Severity.YELLOW
        return Severity.GREEN

    def run(self) -> None:  # noqa: D102 - QThread override
        self._running = True
        if self.monitor_gpu:
            self._gpu_reader = _NvmlGpuReader()

        # Prime psutil's internal counters; first call after this returns
        # a meaningful non-blocking percentage on subsequent calls.
        if self.monitor_cpu:
            psutil.cpu_percent(interval=None)

        while self._running:
            cpu = psutil.cpu_percent(interval=None) if self.monitor_cpu else 0.0
            self._cpu_history.append(cpu)
            if len(self._cpu_history) > 4:
                self._cpu_history.pop(0)
            smoothed_cpu = sum(self._cpu_history) / len(self._cpu_history)

            gpu = self._gpu_reader.read_percent() if (self.monitor_gpu and self._gpu_reader) else None
            sample = SystemSample(
                cpu_percent=round(smoothed_cpu, 1),
                gpu_percent=round(gpu, 1) if gpu is not None else None,
                severity=self._severity_for(smoothed_cpu, gpu),
            )
            self.sample_ready.emit(sample)
            time.sleep(max(0.5, self.poll_interval_seconds))

        if self._gpu_reader:
            self._gpu_reader.shutdown()

    def stop(self) -> None:
        self._running = False
