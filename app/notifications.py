"""Best-effort Windows notification detection.

Reading the *content* of other apps' toast notifications is not something
normal desktop Python code should (or safely can) do, so this module only
ever detects that a notification *arrived* and surfaces a generic label
("NEW NOTIFICATION"), never private message text - matching the privacy-
conscious design called for by the spec.

Real listening requires ``winsdk`` (the modern replacement for the
deprecated ``winrt`` package) plus a registered "Notification Listener"
which itself requires the user to grant access via Windows Settings ->
Notifications, and only works for apps that route through the Windows
Notification/Action Center. This is inherently fragile across Windows
versions, so the watcher degrades to a fully inert (but non-crashing) mode
whenever the API isn't available or access isn't granted, and always
exposes ``simulate()`` so the rest of the app (and users, via the tray
menu / a hotkey) can still trigger the NOTICE behavior manually.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from . import utils

logger = utils.get_logger("notifications")

try:
    # winsdk exposes the WinRT UserNotificationListener API.
    from winsdk.windows.ui.notifications.management import (
        UserNotificationListener,
        UserNotificationListenerAccessStatus,
    )

    _WINSDK_AVAILABLE = True
except ImportError:
    _WINSDK_AVAILABLE = False


class NotificationEvent:
    """Minimal, privacy-safe payload for a detected notification."""

    def __init__(self, label: str = "NEW NOTIFICATION") -> None:
        self.label = label


class _ListenerWorker(QThread):
    """Background poll loop around the WinRT UserNotificationListener.

    Polling (rather than a native event callback) keeps this simple and
    thread-safe to bridge into Qt signals, at the cost of up to ~1s of
    detection latency, which is acceptable for a desktop-pet reaction.
    """

    notification_detected = Signal(object)  # NotificationEvent
    availability_changed = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._running = False
        self._seen_ids: set[int] = set()

    def run(self) -> None:
        import asyncio
        import time

        self._running = True
        if not _WINSDK_AVAILABLE:
            logger.info("winsdk not installed; notification detection disabled")
            self.availability_changed.emit(False)
            return

        try:
            listener = UserNotificationListener.get_current()
            status = asyncio.run(listener.request_access_async())
            if status != UserNotificationListenerAccessStatus.ALLOWED:
                logger.info("Notification listener access not granted (status=%s)", status)
                self.availability_changed.emit(False)
                return
        except Exception:  # noqa: BLE001 - any WinRT hiccup disables this feature gracefully
            logger.exception("Failed to initialize Windows notification listener")
            self.availability_changed.emit(False)
            return

        self.availability_changed.emit(True)
        logger.info("Windows notification listener active")

        while self._running:
            try:
                notifications = asyncio.run(listener.get_notifications_async(0x7FFFFFFF))
                for n in notifications:
                    nid = n.id
                    if nid not in self._seen_ids:
                        self._seen_ids.add(nid)
                        self.notification_detected.emit(NotificationEvent("NEW NOTIFICATION"))
                if len(self._seen_ids) > 500:
                    self._seen_ids.clear()
            except Exception:  # noqa: BLE001
                logger.debug("Notification poll failed this cycle", exc_info=True)
            time.sleep(1.0)

    def stop(self) -> None:
        self._running = False


class NotificationWatcher(QObject):
    """Public facade: emits ``notification`` events; always safe to use.

    Works whether or not the underlying Windows API is available - callers
    (behavior engine, tray menu "test notification" action) don't need to
    know which mode is active.
    """

    notification = Signal(object)  # NotificationEvent
    availability_changed = Signal(bool)

    def __init__(self, enabled: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.enabled = enabled
        self._worker: _ListenerWorker | None = None

    def start(self) -> None:
        if not self.enabled:
            return
        self._worker = _ListenerWorker()
        self._worker.notification_detected.connect(self.notification.emit)
        self._worker.availability_changed.connect(self.availability_changed.emit)
        self._worker.start()

    def stop(self) -> None:
        if self._worker:
            self._worker.stop()
            self._worker.wait(2000)
            self._worker = None

    def simulate(self, label: str = "NEW MESSAGE") -> None:
        """Manually trigger a notification event (tray menu, testing, or as
        the permanent fallback path when the OS API is unavailable)."""
        self.notification.emit(NotificationEvent(label))
