"""Configuration loading, validation, and the Settings UI window.

Keeping validation in one place (``SettingsManager._validate``) means a
corrupt or hand-edited config.json can never crash the rest of the app -
missing or malformed keys are silently replaced with defaults.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import utils

logger = utils.get_logger("settings")

DEFAULT_CONFIG: dict[str, Any] = {
    "pet": {
        "character": "default",
        "scale": 1.0,
        "walk_speed": 2.0,
        "animation_fps": 12,
        "always_on_top": True,
        "monitor_mode": "primary",  # primary | specific_monitor | random_monitor
        "monitor_index": 0,
    },
    "behavior": {
        "idle_min_seconds": 3,
        "idle_max_seconds": 15,
        "jump_probability": 0.02,
        "sleep_probability": 0.005,
        "random_action_probability": 0.01,
    },
    "system": {
        "monitor_cpu": True,
        "monitor_gpu": True,
        "yellow_threshold": 50,
        "red_threshold": 80,
        "poll_interval_seconds": 2.0,
        "show_status_indicator": True,
    },
    "notifications": {
        "enabled": True,
        "board_duration": 3.0,
        "board_position": "above",  # above | side
    },
    "startup": {
        "start_with_windows": False,
        "start_minimized": True,
    },
}


def _deep_merge(base: dict, overrides: dict) -> dict:
    """Recursively merge ``overrides`` on top of ``base`` (defaults)."""
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class SettingsManager:
    """Loads, validates, saves, and provides change notifications for config."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or utils.get_config_path()
        self._config: dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)
        self._listeners: list[Callable[[dict], None]] = []
        self.load()

    # -- persistence -----------------------------------------------------

    def load(self) -> dict:
        if not self.path.exists():
            logger.info("No config.json found, creating defaults at %s", self.path)
            self._config = copy.deepcopy(DEFAULT_CONFIG)
            self.save()
            return self._config

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("config root must be an object")
            self._config = self._validate(raw)
        except Exception as exc:  # noqa: BLE001 - config must never crash startup
            logger.error("Failed to load config.json (%s); falling back to defaults", exc)
            self._config = copy.deepcopy(DEFAULT_CONFIG)
            self.save()
        return self._config

    def save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._config, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.error("Could not write config.json: %s", exc)

    def _validate(self, raw: dict) -> dict:
        """Merge user config over defaults so missing/extra keys never crash."""
        merged = _deep_merge(DEFAULT_CONFIG, raw)

        def clamp(value, lo, hi, fallback):
            try:
                value = float(value)
            except (TypeError, ValueError):
                return fallback
            return max(lo, min(hi, value))

        p = merged["pet"]
        p["scale"] = clamp(p.get("scale"), 0.25, 4.0, DEFAULT_CONFIG["pet"]["scale"])
        p["walk_speed"] = clamp(p.get("walk_speed"), 0.2, 20.0, DEFAULT_CONFIG["pet"]["walk_speed"])
        p["animation_fps"] = int(clamp(p.get("animation_fps"), 4, 60, DEFAULT_CONFIG["pet"]["animation_fps"]))

        s = merged["system"]
        s["yellow_threshold"] = clamp(s.get("yellow_threshold"), 1, 99, 50)
        s["red_threshold"] = clamp(s.get("red_threshold"), 2, 100, 80)
        if s["red_threshold"] <= s["yellow_threshold"]:
            s["red_threshold"] = min(100, s["yellow_threshold"] + 10)
        s["poll_interval_seconds"] = clamp(s.get("poll_interval_seconds"), 0.5, 30.0, 2.0)

        b = merged["behavior"]
        b["idle_min_seconds"] = clamp(b.get("idle_min_seconds"), 0.5, 120, 3)
        b["idle_max_seconds"] = max(b["idle_min_seconds"] + 1, clamp(b.get("idle_max_seconds"), 1, 300, 15))

        return merged

    # -- access ------------------------------------------------------------

    @property
    def config(self) -> dict:
        return self._config

    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self._config
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def update(self, section: str, values: dict) -> None:
        if section not in self._config:
            self._config[section] = {}
        self._config[section].update(values)
        self._config = self._validate(self._config)
        self.save()
        self._notify()

    def on_change(self, callback: Callable[[dict], None]) -> None:
        self._listeners.append(callback)

    def _notify(self) -> None:
        for cb in self._listeners:
            try:
                cb(self._config)
            except Exception:  # noqa: BLE001
                logger.exception("Settings listener raised")


# ---------------------------------------------------------------------------
# Settings UI
# ---------------------------------------------------------------------------
# Imported lazily-safe at module load; PySide6 is a hard dependency of the
# whole app so this is fine to import at top level of a GUI-only module.

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class SettingsWindow(QDialog):
    """Tabbed settings dialog: General / Behavior / System / Notifications / Appearance."""

    def __init__(self, settings: SettingsManager, character_names: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Desktop Companion - Settings")
        self.setMinimumWidth(420)
        self.settings = settings
        self._character_names = character_names or ["default"]

        tabs = QTabWidget(self)
        tabs.addTab(self._build_general_tab(), "General")
        tabs.addTab(self._build_behavior_tab(), "Behavior")
        tabs.addTab(self._build_system_tab(), "System")
        tabs.addTab(self._build_notifications_tab(), "Notifications")
        tabs.addTab(self._build_appearance_tab(), "Appearance")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    # -- tab builders --------------------------------------------------

    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        cfg = self.settings.config

        self.chk_enabled = QCheckBox()
        self.chk_enabled.setChecked(True)
        form.addRow("Enable pet:", self.chk_enabled)

        self.chk_startup = QCheckBox()
        self.chk_startup.setChecked(cfg["startup"]["start_with_windows"])
        form.addRow("Start with Windows:", self.chk_startup)

        self.combo_monitor = QComboBox()
        self.combo_monitor.addItems(["primary", "specific_monitor", "random_monitor"])
        self.combo_monitor.setCurrentText(cfg["pet"]["monitor_mode"])
        form.addRow("Monitor:", self.combo_monitor)

        self.spin_scale = QDoubleSpinBox()
        self.spin_scale.setRange(0.25, 4.0)
        self.spin_scale.setSingleStep(0.1)
        self.spin_scale.setValue(cfg["pet"]["scale"])
        form.addRow("Pet size (scale):", self.spin_scale)

        self.spin_speed = QDoubleSpinBox()
        self.spin_speed.setRange(0.2, 20.0)
        self.spin_speed.setSingleStep(0.5)
        self.spin_speed.setValue(cfg["pet"]["walk_speed"])
        form.addRow("Walking speed (px/tick):", self.spin_speed)

        return w

    def _build_behavior_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        cfg = self.settings.config["behavior"]

        self.spin_idle_min = QSpinBox()
        self.spin_idle_min.setRange(1, 120)
        self.spin_idle_min.setValue(int(cfg["idle_min_seconds"]))
        form.addRow("Idle min (s):", self.spin_idle_min)

        self.spin_idle_max = QSpinBox()
        self.spin_idle_max.setRange(1, 300)
        self.spin_idle_max.setValue(int(cfg["idle_max_seconds"]))
        form.addRow("Idle max (s):", self.spin_idle_max)

        self.spin_jump_prob = QDoubleSpinBox()
        self.spin_jump_prob.setRange(0.0, 1.0)
        self.spin_jump_prob.setSingleStep(0.01)
        self.spin_jump_prob.setDecimals(3)
        self.spin_jump_prob.setValue(cfg["jump_probability"])
        form.addRow("Jump probability / tick:", self.spin_jump_prob)

        self.spin_sleep_prob = QDoubleSpinBox()
        self.spin_sleep_prob.setRange(0.0, 1.0)
        self.spin_sleep_prob.setSingleStep(0.005)
        self.spin_sleep_prob.setDecimals(3)
        self.spin_sleep_prob.setValue(cfg["sleep_probability"])
        form.addRow("Sleep probability / tick:", self.spin_sleep_prob)

        return w

    def _build_system_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        cfg = self.settings.config["system"]

        self.chk_cpu = QCheckBox()
        self.chk_cpu.setChecked(cfg["monitor_cpu"])
        form.addRow("Monitor CPU:", self.chk_cpu)

        self.chk_gpu = QCheckBox()
        self.chk_gpu.setChecked(cfg["monitor_gpu"])
        form.addRow("Monitor GPU:", self.chk_gpu)

        self.spin_yellow = QSpinBox()
        self.spin_yellow.setRange(1, 99)
        self.spin_yellow.setValue(int(cfg["yellow_threshold"]))
        form.addRow("Yellow threshold (%):", self.spin_yellow)

        self.spin_red = QSpinBox()
        self.spin_red.setRange(2, 100)
        self.spin_red.setValue(int(cfg["red_threshold"]))
        form.addRow("Red threshold (%):", self.spin_red)

        self.chk_indicator = QCheckBox()
        self.chk_indicator.setChecked(cfg["show_status_indicator"])
        form.addRow("Show status indicator:", self.chk_indicator)

        return w

    def _build_notifications_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        cfg = self.settings.config["notifications"]

        self.chk_notif = QCheckBox()
        self.chk_notif.setChecked(cfg["enabled"])
        form.addRow("Enable notifications:", self.chk_notif)

        self.spin_duration = QDoubleSpinBox()
        self.spin_duration.setRange(1.0, 30.0)
        self.spin_duration.setValue(cfg["board_duration"])
        form.addRow("Board duration (s):", self.spin_duration)

        self.combo_position = QComboBox()
        self.combo_position.addItems(["above", "side"])
        self.combo_position.setCurrentText(cfg["board_position"])
        form.addRow("Board position:", self.combo_position)

        return w

    def _build_appearance_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self.combo_character = QComboBox()
        self.combo_character.addItems(self._character_names)
        current = self.settings.config["pet"]["character"]
        if current in self._character_names:
            self.combo_character.setCurrentText(current)
        form.addRow("Character:", self.combo_character)

        form.addRow(QLabel("Always-on-top and status indicator are controlled here"))
        self.chk_always_on_top = QCheckBox()
        self.chk_always_on_top.setChecked(self.settings.config["pet"]["always_on_top"])
        form.addRow("Always on top:", self.chk_always_on_top)

        return w

    # -- persistence -----------------------------------------------------

    def _on_accept(self) -> None:
        self.settings.update(
            "pet",
            {
                "character": self.combo_character.currentText(),
                "scale": self.spin_scale.value(),
                "walk_speed": self.spin_speed.value(),
                "monitor_mode": self.combo_monitor.currentText(),
                "always_on_top": self.chk_always_on_top.isChecked(),
            },
        )
        self.settings.update(
            "behavior",
            {
                "idle_min_seconds": self.spin_idle_min.value(),
                "idle_max_seconds": self.spin_idle_max.value(),
                "jump_probability": self.spin_jump_prob.value(),
                "sleep_probability": self.spin_sleep_prob.value(),
            },
        )
        self.settings.update(
            "system",
            {
                "monitor_cpu": self.chk_cpu.isChecked(),
                "monitor_gpu": self.chk_gpu.isChecked(),
                "yellow_threshold": self.spin_yellow.value(),
                "red_threshold": self.spin_red.value(),
                "show_status_indicator": self.chk_indicator.isChecked(),
            },
        )
        self.settings.update(
            "notifications",
            {
                "enabled": self.chk_notif.isChecked(),
                "board_duration": self.spin_duration.value(),
                "board_position": self.combo_position.currentText(),
            },
        )
        self.settings.update("startup", {"start_with_windows": self.chk_startup.isChecked()})
        self.accept()
