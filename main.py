"""Desktop Companion - entry point.

Boots the Qt application, runs the first-run character setup if needed,
then wires together settings, the pet, its window, the system monitor,
the notification watcher, and the tray icon.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog

from app import utils
from app.character import CharacterManager
from app.first_run import ensure_character_exists
from app.notifications import NotificationWatcher
from app.pet import Pet
from app.pet_window import PetWindow
from app.settings import SettingsManager, SettingsWindow
from app.startup import set_enabled as set_startup_enabled
from app.system_monitor import SystemMonitor
from app.tray import TrayIcon

logger = utils.get_logger("main")


class Application:
    """Owns the long-lived objects and connects their signals."""

    def __init__(self) -> None:
        self.settings = SettingsManager()
        self.character_manager = CharacterManager()

        self.pet = Pet(self.settings.config)
        self.window = PetWindow(self.pet, self.settings.config)

        self.tray = TrayIcon(self.settings.config)
        self.notifications = NotificationWatcher(enabled=self.settings.config["notifications"]["enabled"])
        self.monitor = self._build_monitor()

        self._wire_signals()

        self.window.show()
        self.tray.show()
        self.monitor.start()
        self.notifications.start()

    # -- construction helpers ---------------------------------------------

    def _build_monitor(self) -> SystemMonitor:
        sys_cfg = self.settings.config["system"]
        return SystemMonitor(
            poll_interval_seconds=sys_cfg["poll_interval_seconds"],
            monitor_cpu=sys_cfg["monitor_cpu"],
            monitor_gpu=sys_cfg["monitor_gpu"],
            yellow_threshold=sys_cfg["yellow_threshold"],
            red_threshold=sys_cfg["red_threshold"],
        )

    def _wire_signals(self) -> None:
        # System monitor -> pet behavior + window indicator
        self.monitor.sample_ready.connect(self._on_system_sample)

        # Notifications -> pet behavior + window board
        self.notifications.notification.connect(self._on_notification)

        # Pet window -> settings dialog / exit
        self.window.settings_requested.connect(self.open_settings)
        self.window.exit_requested.connect(self.quit)

        # Tray menu -> various actions
        self.tray.open_settings_requested.connect(self.open_settings)
        self.tray.pause_requested.connect(lambda: self._set_paused(True))
        self.tray.resume_requested.connect(lambda: self._set_paused(False))
        self.tray.change_character_requested.connect(self.change_character)
        self.tray.reload_character_requested.connect(self.reload_character)
        self.tray.toggle_indicator_requested.connect(self._toggle_indicator)
        self.tray.toggle_notifications_requested.connect(self._toggle_notifications)
        self.tray.toggle_startup_requested.connect(self._toggle_startup)
        self.tray.test_notification_requested.connect(lambda: self.notifications.simulate("NEW MESSAGE"))
        self.tray.exit_requested.connect(self.quit)

        self.settings.on_change(self._on_settings_changed)

    # -- event handlers ------------------------------------------------------

    def _on_system_sample(self, sample) -> None:
        self.pet.on_system_severity(sample.severity)
        self.window.update_severity(sample.severity)

    def _on_notification(self, event) -> None:
        if not self.settings.config["notifications"]["enabled"]:
            return
        self.pet.on_notification()
        self.window.show_notification_board(event.label, self.settings.config["notifications"]["board_duration"])

    def _set_paused(self, paused: bool) -> None:
        self.window.set_paused(paused)
        self.tray.notify_paused(paused)

    def open_settings(self) -> None:
        names = self.character_manager.list_names()
        dialog = SettingsWindow(self.settings, names)
        dialog.exec()

    def change_character(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(None, "Choose a character PNG", "", "PNG Images (*.png)")
        if not file_path:
            return
        name, ok = QInputDialog.getText(None, "Character Name", "Enter a name for this character:")
        if not ok or not name.strip():
            return
        name = name.strip().replace(" ", "_")
        self.character_manager.import_png(name, Path(file_path))
        self.settings.update("pet", {"character": name})
        self.reload_character()

    def reload_character(self) -> None:
        cfg = self.settings.config
        if self.pet.load_character(cfg["pet"]["character"], cfg["pet"]["scale"]):
            self.window.apply_config(cfg)
            logger.info("Character reloaded without restarting the application")

    def _toggle_indicator(self, checked: bool) -> None:
        self.settings.update("system", {"show_status_indicator": checked})

    def _toggle_notifications(self, checked: bool) -> None:
        self.settings.update("notifications", {"enabled": checked})

    def _toggle_startup(self, checked: bool) -> None:
        success = set_startup_enabled(checked)
        self.settings.update("startup", {"start_with_windows": checked if success else False})

    def _on_settings_changed(self, config: dict) -> None:
        self.pet.set_scale(config["pet"]["scale"])
        self.pet.set_walk_speed(config["pet"]["walk_speed"])
        self.pet.refresh_bounds(config["pet"]["monitor_mode"], config["pet"].get("monitor_index", 0))
        self.pet.behavior.update_config(config["behavior"])
        self.monitor.monitor_cpu = config["system"]["monitor_cpu"]
        self.monitor.monitor_gpu = config["system"]["monitor_gpu"]
        self.monitor.update_thresholds(config["system"]["yellow_threshold"], config["system"]["red_threshold"])
        self.window.apply_config(config)

    def quit(self) -> None:
        logger.info("Shutting down")
        self.monitor.stop()
        self.monitor.wait(2000)
        self.notifications.stop()
        QApplication.instance().quit()


def main() -> int:
    utils.setup_logging()
    logger.info("Starting Desktop Companion")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # tray icon keeps the app alive

    if not ensure_character_exists():
        logger.warning("No character selected on first run; exiting")
        return 1

    controller = Application()
    # Keep a reference on the QApplication so nothing gets garbage collected.
    app._companion_controller = controller  # type: ignore[attr-defined]

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
