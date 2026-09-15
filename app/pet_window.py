"""The only module that actually draws pixels on screen.

A small, borderless, transparent, click-through-except-on-the-sprite
``QWidget`` that repaints on a QTimer tick. It reads a ``RenderFrame``
from :class:`app.pet.Pet` each tick and applies the transform - it does
not decide *what* to draw, only *how*.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QWidget

from .animation import PetState, Transform
from .pet import Pet, RenderFrame
from .system_monitor import Severity
from . import utils

logger = utils.get_logger("pet_window")

# Extra canvas padding around the sprite so rotation/scale/jump don't clip.
CANVAS_PADDING = 120
BOARD_HEIGHT = 46


class SleepBubble:
    """Small floating "Z" letters drawn near the character's head while
    asleep - purely decorative, driven by the state's own elapsed time so
    it loops smoothly regardless of tick rate."""

    _LETTERS = "Zzz"

    def paint(self, painter: QPainter, anchor_x: int, anchor_y: int, elapsed: float) -> None:
        painter.save()
        font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        for i, letter in enumerate(self._LETTERS):
            cycle = (elapsed * 0.8 + i * 0.35) % 1.0
            rise = cycle * 26.0
            fade = 1.0 - cycle
            size = 9 + i * 3
            f = QFont(font)
            f.setPointSize(size)
            painter.setFont(f)
            painter.setOpacity(max(0.0, fade))
            painter.setPen(QColor(70, 70, 90, 255))
            painter.drawText(int(anchor_x + i * 10), int(anchor_y - rise), letter)
        painter.restore()


class NotificationBoard:
    """A tiny sign drawn above the pet; not a separate window/widget so it
    can never intercept clicks meant for the character."""

    def __init__(self) -> None:
        self.visible = False
        self.text = ""
        self._hide_timer: QTimer | None = None

    def show(self, text: str, duration_seconds: float, on_hide) -> None:
        self.visible = True
        self.text = text
        if self._hide_timer:
            self._hide_timer.stop()
        self._hide_timer = QTimer()
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(lambda: self._do_hide(on_hide))
        self._hide_timer.start(int(duration_seconds * 1000))

    def _do_hide(self, on_hide) -> None:
        self.visible = False
        on_hide()

    def paint(self, painter: QPainter, canvas_width: int, sprite_top: int) -> None:
        if not self.visible:
            return
        board_width = 130
        x = (canvas_width - board_width) // 2
        y = max(0, sprite_top - BOARD_HEIGHT - 8)

        painter.save()
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.setPen(QColor(60, 60, 60, 255))
        painter.drawRoundedRect(x, y, board_width, BOARD_HEIGHT, 8, 8)
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.setPen(QColor(30, 30, 30, 255))
        painter.drawText(x, y, board_width, BOARD_HEIGHT, Qt.AlignmentFlag.AlignCenter, self.text)
        painter.restore()


class StatusIndicator:
    """Small colored dot reflecting CPU/GPU severity."""

    _COLORS = {
        Severity.GREEN: QColor(70, 200, 90, 230),
        Severity.YELLOW: QColor(240, 190, 40, 230),
        Severity.RED: QColor(230, 60, 60, 230),
    }

    def __init__(self) -> None:
        self.enabled = True
        self.severity = Severity.GREEN

    def paint(self, painter: QPainter, sprite_x: int, sprite_y: int, sprite_w: int) -> None:
        if not self.enabled:
            return
        radius = 7
        cx = sprite_x + sprite_w - radius
        cy = sprite_y + radius + 2
        painter.save()
        painter.setBrush(self._COLORS[self.severity])
        painter.setPen(QColor(255, 255, 255, 200))
        painter.drawEllipse(QPoint(cx, cy), radius, radius)
        painter.restore()


class PetWindow(QWidget):
    settings_requested = Signal()
    exit_requested = Signal()

    def __init__(self, pet: Pet, config: dict) -> None:
        super().__init__()
        self.pet = pet
        self.config = config
        self.board = NotificationBoard()
        self.indicator = StatusIndicator()
        self.sleep_bubble = SleepBubble()
        self.indicator.enabled = config["system"]["show_status_indicator"]
        self._paused = False
        self._current_frame: RenderFrame | None = None
        self._drag_active = False

        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        if not config["pet"]["always_on_top"]:
            flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        w, h = pet.pixel_size()
        self.resize(w + CANVAS_PADDING * 2, h + CANVAS_PADDING * 2 + BOARD_HEIGHT + 8)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_tick)
        self._apply_fps(config["pet"]["animation_fps"])
        self.timer.start()

    # -- lifecycle / config changes ---------------------------------------

    def _apply_fps(self, fps: int) -> None:
        interval_ms = max(16, int(1000 / max(1, fps)))
        self.timer.setInterval(interval_ms)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def apply_config(self, config: dict) -> None:
        self.config = config
        self.indicator.enabled = config["system"]["show_status_indicator"]
        self._apply_fps(config["pet"]["animation_fps"])
        w, h = self.pet.pixel_size()
        self.resize(w + CANVAS_PADDING * 2, h + CANVAS_PADDING * 2 + BOARD_HEIGHT + 8)

    def show_notification_board(self, text: str, duration: float) -> None:
        self.board.show(text, duration, on_hide=self.update)
        self.update()

    def update_severity(self, severity: Severity) -> None:
        self.indicator.severity = severity

    # -- tick / paint -------------------------------------------------------

    def _on_tick(self) -> None:
        if self._paused:
            return
        self._current_frame = self.pet.update()
        # Keep the window itself glued to the sprite's screen position;
        # the sprite is drawn centered within the padded canvas.
        self.move(int(self._current_frame.x) - CANVAS_PADDING, int(self._current_frame.y) - CANVAS_PADDING)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        if self._current_frame is None:
            return

        frame = self._current_frame
        transform = frame.transform
        pixmap = frame.pixmap

        sprite_x = CANVAS_PADDING
        sprite_y = CANVAS_PADDING + BOARD_HEIGHT + 8

        painter.save()
        painter.setOpacity(max(0.0, min(1.0, transform.opacity)))

        pivot_y_local = pixmap.height() if transform.pivot_at_base else pixmap.height() / 2
        cx = sprite_x + pixmap.width() / 2 + transform.offset_x
        cy = sprite_y + pivot_y_local + transform.offset_y
        painter.translate(cx, cy)
        painter.rotate(transform.rotation_deg)
        painter.scale(transform.scale_x, transform.scale_y)
        painter.translate(-pixmap.width() / 2, -pivot_y_local)
        painter.drawPixmap(0, 0, pixmap)
        painter.restore()

        self.board.paint(painter, self.width(), sprite_y)
        self.indicator.paint(painter, sprite_x, sprite_y, pixmap.width())
        if frame.state == PetState.SLEEP:
            self.sleep_bubble.paint(painter, int(cx), int(cy - pixmap.height() * 0.3), frame.state_elapsed)

    # -- interaction ---------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._sprite_hit(event.position().toPoint()):
            event.ignore()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.pet.on_user_click("EXCITED")
        elif event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._sprite_hit(event.position().toPoint()):
            self.settings_requested.emit()

    def _sprite_hit(self, point: QPoint) -> bool:
        if self._current_frame is None:
            return False
        pm = self._current_frame.pixmap
        sprite_x = CANVAS_PADDING
        sprite_y = CANVAS_PADDING + BOARD_HEIGHT + 8
        return (
            sprite_x - 10 <= point.x() <= sprite_x + pm.width() + 10
            and sprite_y - 10 <= point.y() <= sprite_y + pm.height() + 10
        )

    def _show_context_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        jump_action = menu.addAction("Jump")
        settings_action = menu.addAction("Open Settings")
        menu.addSeparator()
        exit_action = menu.addAction("Exit")

        chosen = menu.exec(global_pos)
        if chosen == jump_action:
            self.pet.on_user_click("JUMP")
        elif chosen == settings_action:
            self.settings_requested.emit()
        elif chosen == exit_action:
            self.exit_requested.emit()
