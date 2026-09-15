"""The ``Pet`` glues character assets + animation + movement + behavior
together into one per-tick update, but deliberately knows nothing about
Qt windows or painting - :class:`app.pet_window.PetWindow` is the only
place pixels actually get drawn, keeping rendering separate from logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from .animation import AnimationEngine, PetState, Transform
from .behavior import BehaviorEngine
from .character import CharacterManager
from .image_processor import ImageProcessor, ProcessedCharacter
from .movement import Bounds, Direction, MovementController, ScreenSelector
from . import utils

logger = utils.get_logger("pet")


@dataclass
class RenderFrame:
    """Everything :class:`PetWindow` needs to paint one frame."""

    pixmap: QPixmap
    x: float
    y: float
    transform: Transform
    state: PetState


class Pet:
    def __init__(self, config: dict) -> None:
        self._character_manager = CharacterManager()
        self._image_processor = ImageProcessor()
        self.animation = AnimationEngine(fps=config["pet"]["animation_fps"])
        self.behavior = BehaviorEngine(config["behavior"])

        self._pixmaps: dict[str, QPixmap] = {}
        self._processed: ProcessedCharacter | None = None
        self.scale = config["pet"]["scale"]
        self.walk_speed = config["pet"]["walk_speed"]

        self._last_seen_state: PetState = PetState.IDLE
        self.load_character(config["pet"]["character"], config["pet"]["scale"])

        base_w, base_h = self.pixel_size()
        bounds = ScreenSelector.choose_geometry(
            config["pet"]["monitor_mode"], config["pet"].get("monitor_index", 0), base_h
        )
        self.movement = MovementController(bounds, base_w, self.walk_speed)

    # -- character / assets -------------------------------------------------

    def load_character(self, name: str, scale: float) -> bool:
        info = self._character_manager.get(name) or self._character_manager.get("default")
        if info is None:
            logger.error("No character available (missing assets/characters/*/character.png)")
            return False

        processed = self._image_processor.process(info.name, info.source_png)
        if processed is None:
            logger.error("Character processing failed for '%s'", info.name)
            return False

        self._processed = processed
        self.scale = scale
        right = QPixmap(str(processed.right_facing_path))
        left = QPixmap(str(processed.left_facing_path))
        target_h = max(1, int(processed.height * scale))
        target_w = max(1, int(processed.width * scale))
        self._pixmaps = {
            "right": right.scaled(
                target_w, target_h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
            ),
            "left": left.scaled(
                target_w, target_h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
            ),
        }
        logger.info("Loaded character '%s' at scale %.2f -> %dx%d", info.name, scale, target_w, target_h)
        return True

    def pixel_size(self) -> tuple[int, int]:
        if not self._pixmaps:
            return (100, 100)
        pm = self._pixmaps["right"]
        return (pm.width(), pm.height())

    def set_scale(self, scale: float) -> None:
        if self._processed is None:
            return
        self.load_character(self._processed.name, scale)
        w, h = self.pixel_size()
        self.movement.update_bounds(self.movement.bounds, w)

    def set_walk_speed(self, speed: float) -> None:
        self.walk_speed = speed
        self.movement.walk_speed = speed

    def refresh_bounds(self, monitor_mode: str, monitor_index: int) -> None:
        _, h = self.pixel_size()
        bounds = ScreenSelector.choose_geometry(monitor_mode, monitor_index, h)
        w, _ = self.pixel_size()
        self.movement.update_bounds(bounds, w)

    # -- per-tick update -----------------------------------------------------

    def update(self) -> RenderFrame:
        hit_edge = False
        state = self.behavior.state

        if state == PetState.WALK:
            hit_edge = self.movement.step()

        if state == PetState.TURN and self._last_seen_state != PetState.TURN:
            # Flip direction exactly once, on the first tick we observe TURN.
            self.movement.pick_new_direction_away_from_edge()
        self._last_seen_state = state

        new_state = self.behavior.tick(hit_edge)

        facing_left = self.movement.direction == Direction.LEFT
        pixmap = self._pixmaps["left" if facing_left else "right"]
        transform = self.animation.compute(new_state, self.behavior.elapsed_in_state(), facing_left)

        return RenderFrame(pixmap=pixmap, x=self.movement.x, y=self.movement.y, transform=transform, state=new_state)

    # -- external events -----------------------------------------------------

    def on_notification(self) -> None:
        self.behavior.notify()

    def on_system_severity(self, severity) -> None:
        self.behavior.set_severity(severity)

    def on_user_click(self, state_name: str = "EXCITED") -> None:
        self.behavior.trigger(state_name)
