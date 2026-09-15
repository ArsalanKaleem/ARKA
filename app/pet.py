"""The ``Pet`` glues character assets + animation + movement + behavior
together into one per-tick update, but deliberately knows nothing about
Qt *windows* or painting them to screen - :class:`app.pet_window.PetWindow`
is the only place pixels actually land on the desktop. ``Pet`` does,
however, own the small QPainter composite step that glues the torso and
two leg layers into one frame when a state needs moving limbs (see
``_compose_walk_frame``), since that's asset work, not screen rendering.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter, QPixmap, QTransform

from .animation import AnimationEngine, LimbPose, PetState, Transform
from .behavior import BehaviorEngine
from .character import CharacterManager
from .image_processor import ImageProcessor, ProcessedCharacter, RigAssets
from .movement import Direction, MovementController, ScreenSelector
from . import utils

logger = utils.get_logger("pet")

# States whose rig needs an actual per-frame recomposite (moving legs).
# Everything else just reuses the plain static pixmap - cheaper, and looks
# identical to the rig at rest anyway.
_RIGGED_STATES = {PetState.WALK, PetState.JUMP, PetState.PANIC}


@dataclass
class RenderFrame:
    """Everything :class:`PetWindow` needs to paint one frame."""

    pixmap: QPixmap
    x: float
    y: float
    transform: Transform
    state: PetState
    state_elapsed: float


class _RigPixmaps:
    """QPixmap versions of one facing direction's torso/leg layers."""

    __slots__ = ("torso", "leg_a", "leg_b", "pivot_x", "pivot_y", "canvas_size")

    def __init__(self, rig: RigAssets, scale: float) -> None:
        torso_src = QPixmap(str(rig.torso_path))
        leg_a_src = QPixmap(str(rig.leg_a_path))
        leg_b_src = QPixmap(str(rig.leg_b_path))
        w = max(1, int(torso_src.width() * scale))
        h = max(1, int(torso_src.height() * scale))
        mode = (Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.torso = torso_src.scaled(w, h, *mode)
        self.leg_a = leg_a_src.scaled(w, h, *mode)
        self.leg_b = leg_b_src.scaled(w, h, *mode)
        self.pivot_x = rig.pivot_x * scale
        self.pivot_y = rig.pivot_y * scale
        self.canvas_size = (w, h)


class Pet:
    def __init__(self, config: dict) -> None:
        self._character_manager = CharacterManager()
        self._image_processor = ImageProcessor()
        self.animation = AnimationEngine(fps=config["pet"]["animation_fps"])
        self.behavior = BehaviorEngine(config["behavior"])

        self._pixmaps: dict[str, QPixmap] = {}
        self._rigs: dict[str, _RigPixmaps] = {}
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
        mode = (Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        right = QPixmap(str(processed.right_facing_path))
        left = QPixmap(str(processed.left_facing_path))
        target_w = max(1, int(processed.width * scale))
        target_h = max(1, int(processed.height * scale))
        self._pixmaps = {
            "right": right.scaled(target_w, target_h, *mode),
            "left": left.scaled(target_w, target_h, *mode),
        }
        self._rigs = {
            "right": _RigPixmaps(processed.rig_right, scale),
            "left": _RigPixmaps(processed.rig_left, scale),
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

    # -- rig compositing -----------------------------------------------------

    def _compose_rig_frame(self, facing_key: str, pose: LimbPose) -> QPixmap:
        """Paint torso + two rotated leg layers into one transparent canvas.

        Both leg layers share the same pivot (see ``image_processor``), so
        at angle 0 this reproduces the plain image exactly; small opposing
        angles create the alternating leg-swing walk cycle.
        """
        rig = self._rigs[facing_key]
        canvas = QPixmap(*rig.canvas_size)
        canvas.fill(Qt.GlobalColor.transparent)

        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pivot = QPointF(rig.pivot_x, rig.pivot_y)

        for leg, angle in ((rig.leg_a, pose.leg_a_deg), (rig.leg_b, pose.leg_b_deg)):
            painter.save()
            painter.translate(pivot)
            painter.rotate(angle)
            painter.translate(-pivot)
            painter.drawPixmap(0, 0, leg)
            painter.restore()

        # Torso drawn last (on top), with a tiny shear to imply counter-
        # swinging shoulders/arms without a separate arm cutout.
        painter.save()
        transform = QTransform()
        transform.translate(pivot.x(), 0)
        transform.shear(pose.torso_shear, 0)
        transform.translate(-pivot.x(), 0)
        painter.setTransform(transform, combine=True)
        painter.drawPixmap(0, 0, rig.torso)
        painter.restore()

        painter.end()
        return canvas

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
        state_elapsed = self.behavior.elapsed_in_state()

        facing_left = self.movement.direction == Direction.LEFT
        facing_key = "left" if facing_left else "right"

        pose = self.animation.limb_pose(new_state, state_elapsed)
        if pose is not None and new_state in _RIGGED_STATES:
            pixmap = self._compose_rig_frame(facing_key, pose)
        else:
            pixmap = self._pixmaps[facing_key]

        transform = self.animation.compute(new_state, state_elapsed, facing_left)

        return RenderFrame(
            pixmap=pixmap,
            x=self.movement.x,
            y=self.movement.y,
            transform=transform,
            state=new_state,
            state_elapsed=state_elapsed,
        )

    # -- external events -----------------------------------------------------

    def on_notification(self) -> None:
        self.behavior.notify()

    def on_system_severity(self, severity) -> None:
        self.behavior.set_severity(severity)

    def on_user_click(self, state_name: str = "EXCITED") -> None:
        self.behavior.trigger(state_name)
