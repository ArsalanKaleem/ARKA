"""Procedural, single-image animation engine.

No animation frames or spritesheets are needed: every state is expressed
as a small set of *transform* values (vertical bob, rotation, scale,
horizontal flip, opacity) that change over time following simple periodic
or eased functions. ``PetWindow`` reads a ``Transform`` each tick and
applies it when painting the single cached QPixmap - it has no idea what
CPU usage or notifications are, keeping animation decoupled from behavior
per the architecture rule (animation must not know about system state).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto


class PetState(Enum):
    IDLE = auto()
    WALK = auto()
    JUMP = auto()
    FALL = auto()
    SLEEP = auto()
    NOTICE = auto()
    EXCITED = auto()
    PANIC = auto()
    TURN = auto()


@dataclass
class Transform:
    """A single frame's visual transform, applied on top of base position."""

    offset_x: float = 0.0
    offset_y: float = 0.0
    rotation_deg: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    opacity: float = 1.0
    facing_left: bool = False


class AnimationEngine:
    """Computes a :class:`Transform` for the current state and elapsed time.

    ``elapsed`` is state-local seconds (reset whenever the state changes),
    which keeps each animation's phase predictable regardless of how long
    the pet spent in a previous state.
    """

    def __init__(self, fps: int = 12) -> None:
        self.fps = fps

    def compute(self, state: PetState, elapsed: float, facing_left: bool) -> Transform:
        handler = getattr(self, f"_{state.name.lower()}", self._idle)
        transform = handler(elapsed)
        transform.facing_left = facing_left
        return transform

    # -- individual state animations -------------------------------------

    def _idle(self, t: float) -> Transform:
        # Gentle breathing bob.
        bob = math.sin(t * 2.0) * 2.0
        return Transform(offset_y=bob, scale_y=1.0 + math.sin(t * 2.0) * 0.01)

    def _walk(self, t: float) -> Transform:
        # Bounce + slight rocking rotation gives the illusion of footsteps
        # even though it's the same static sprite each frame.
        stride = t * 6.0
        bob = abs(math.sin(stride)) * -4.0
        rotation = math.sin(stride) * 3.0
        squash = 1.0 - abs(math.sin(stride)) * 0.03
        return Transform(offset_y=bob, rotation_deg=rotation, scale_x=1.0 + (1 - squash), scale_y=squash)

    def _jump(self, t: float) -> Transform:
        duration = 0.6
        progress = min(t / duration, 1.0)
        # Simple parabolic arc, peaking at the midpoint.
        height = -60.0 * (4 * progress * (1 - progress))
        stretch = 1.0 + 0.15 * math.sin(progress * math.pi)
        return Transform(offset_y=height, scale_x=1.0 / stretch, scale_y=stretch)

    def _fall(self, t: float) -> Transform:
        drop = min(t * t * 300.0, 200.0)
        return Transform(offset_y=drop, scale_y=1.08, scale_x=0.94)

    def _sleep(self, t: float) -> Transform:
        breathe = math.sin(t * 1.0) * 1.5
        return Transform(offset_y=breathe, rotation_deg=8.0, opacity=0.9)

    def _notice(self, t: float) -> Transform:
        wobble = math.sin(t * 8.0) * 4.0 if t < 0.6 else 0.0
        return Transform(rotation_deg=wobble)

    def _excited(self, t: float) -> Transform:
        bounce = abs(math.sin(t * 10.0)) * -10.0
        wiggle = math.sin(t * 10.0) * 6.0
        return Transform(offset_y=bounce, rotation_deg=wiggle)

    def _panic(self, t: float) -> Transform:
        shake = math.sin(t * 25.0) * 5.0
        bob = abs(math.sin(t * 14.0)) * -6.0
        return Transform(offset_x=shake, offset_y=bob, rotation_deg=shake * 0.6)

    def _turn(self, t: float) -> Transform:
        duration = 0.25
        progress = min(t / duration, 1.0)
        squeeze = 1.0 - 0.6 * math.sin(progress * math.pi)
        return Transform(scale_x=max(0.15, squeeze))
