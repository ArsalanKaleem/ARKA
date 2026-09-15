"""Windows system tray icon with the pause/resume/settings/exit menu."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import utils

logger = utils.get_logger("tray")


def _make_fallback_icon() -> QIcon:
    """A tiny generated icon so the tray never fails for lack of an .ico file."""
    pm = QPixmap(32, 32)
    pm.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(120, 170, 250))
    painter.setPen(QColor(255, 255, 255))
    painter.drawEllipse(2, 2, 28, 28)
    painter.end()
    return QIcon(pm)


class TrayIcon(QSystemTrayIcon):
    open_settings_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    change_character_requested = Signal()
    reload_character_requested = Signal()
    toggle_indicator_requested = Signal(bool)
    toggle_notifications_requested = Signal(bool)
    toggle_startup_requested = Signal(bool)
    test_notification_requested = Signal()
    exit_requested = Signal()

    def __init__(self, config: dict, parent=None) -> None:
        icon_path = utils.get_assets_dir() / "ui" / "tray_icon.png"
        icon = QIcon(str(icon_path)) if icon_path.exists() else _make_fallback_icon()
        super().__init__(icon, parent)
        self.setToolTip("Desktop Companion")

        self._menu = QMenu()
        self._build_menu(config)
        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)

    def _build_menu(self, config: dict) -> None:
        menu = self._menu

        act_settings = menu.addAction("Open Settings")
        act_settings.triggered.connect(self.open_settings_requested.emit)

        menu.addSeparator()

        self._act_pause = QAction("Pause Pet", checkable=True)
        self._act_pause.toggled.connect(
            lambda checked: (self.pause_requested if checked else self.resume_requested).emit()
        )
        menu.addAction(self._act_pause)

        menu.addSeparator()

        act_change_char = menu.addAction("Change Character")
        act_change_char.triggered.connect(self.change_character_requested.emit)

        act_reload_char = menu.addAction("Reload Character")
        act_reload_char.triggered.connect(self.reload_character_requested.emit)

        menu.addSeparator()

        self._act_indicator = QAction("Toggle Status Indicator", checkable=True)
        self._act_indicator.setChecked(config["system"]["show_status_indicator"])
        self._act_indicator.toggled.connect(self.toggle_indicator_requested.emit)
        menu.addAction(self._act_indicator)

        self._act_notifications = QAction("Toggle Notifications", checkable=True)
        self._act_notifications.setChecked(config["notifications"]["enabled"])
        self._act_notifications.toggled.connect(self.toggle_notifications_requested.emit)
        menu.addAction(self._act_notifications)

        act_test_notif = menu.addAction("Send Test Notification")
        act_test_notif.triggered.connect(self.test_notification_requested.emit)

        self._act_startup = QAction("Start With Windows", checkable=True)
        self._act_startup.setChecked(config["startup"]["start_with_windows"])
        self._act_startup.toggled.connect(self.toggle_startup_requested.emit)
        menu.addAction(self._act_startup)

        menu.addSeparator()

        act_about = menu.addAction("About")
        act_about.triggered.connect(self._show_about)

        act_exit = menu.addAction("Exit")
        act_exit.triggered.connect(self.exit_requested.emit)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_settings_requested.emit()

    def _show_about(self) -> None:
        self.showMessage(
            "Desktop Companion",
            "A lightweight animated desktop pet built with Python + PySide6.",
            QSystemTrayIcon.MessageIcon.Information,
            4000,
        )

    def notify_paused(self, paused: bool) -> None:
        self._act_pause.blockSignals(True)
        self._act_pause.setChecked(paused)
        self._act_pause.blockSignals(False)
