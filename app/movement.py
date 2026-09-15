"""Screen-space movement: walking position, direction, and edge detection.

Deliberately has no knowledge of *why* the pet is moving (that's the
behavior engine's job) - it just knows how to advance an (x, y) position
within the chosen monitor's bounds and report when an edge is hit.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication, QScreen

from . import utils

logger = utils.get_logger("movement")


class Direction(Enum):
    LEFT = -1
    RIGHT = 1


@dataclass
class Bounds:
    left: int
    right: int
    ground_y: int  # y coordinate (top of pet) that represents "standing on the taskbar-free bottom"


class ScreenSelector:
    """Resolves which monitor's geometry the pet should live within."""

    @staticmethod
    def available_screens() -> list[QScreen]:
        screens = QGuiApplication.screens()
        return list(screens) if screens else []

    @classmethod
    def choose_geometry(cls, monitor_mode: str, monitor_index: int, pet_height: int) -> Bounds:
        screens = cls.available_screens()
        if not screens:
            # Extremely defensive fallback if Qt can't enumerate screens at all.
            return Bounds(left=0, right=1280, ground_y=720 - pet_height)

        if monitor_mode == "specific_monitor" and 0 <= monitor_index < len(screens):
            screen = screens[monitor_index]
        elif monitor_mode == "random_monitor":
            screen = random.choice(screens)
        else:
            screen = QGuiApplication.primaryScreen() or screens[0]

        geo: QRect = screen.availableGeometry()
        margin = 4
        return Bounds(
            left=geo.left() + margin,
            right=geo.right() - margin,
            ground_y=geo.bottom() - pet_height,
        )


class MovementController:
    """Owns the pet's current (x, y) position and walking direction."""

    def __init__(self, bounds: Bounds, pet_width: int, walk_speed: float) -> None:
        self.bounds = bounds
        self.pet_width = pet_width
        self.walk_speed = walk_speed
        self.x = float(random.randint(bounds.left, max(bounds.left, bounds.right - pet_width)))
        self.y = float(bounds.ground_y)
        self.direction = random.choice([Direction.LEFT, Direction.RIGHT])

    def update_bounds(self, bounds: Bounds, pet_width: int) -> None:
        self.bounds = bounds
        self.pet_width = pet_width
        self.x = min(self.x, bounds.right - pet_width)
        self.y = bounds.ground_y

    def hit_left_edge(self) -> bool:
        return self.x <= self.bounds.left

    def hit_right_edge(self) -> bool:
        return self.x + self.pet_width >= self.bounds.right

    def step(self) -> bool:
        """Advance one walking tick. Returns True if an edge was hit this step."""
        self.x += self.direction.value * self.walk_speed
        self.x = max(self.bounds.left, min(self.x, self.bounds.right - self.pet_width))
        return self.hit_left_edge() or self.hit_right_edge()

    def turn_around(self) -> None:
        self.direction = Direction.LEFT if self.direction == Direction.RIGHT else Direction.RIGHT

    def pick_new_direction_away_from_edge(self) -> None:
        if self.hit_left_edge():
            self.direction = Direction.RIGHT
        elif self.hit_right_edge():
            self.direction = Direction.LEFT
