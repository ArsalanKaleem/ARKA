"""Animation math: what should move, by how much, and how fast.

Two kinds of output per tick:

* ``LimbPose`` - angles for the two independently-rotating leg layers
  (see ``image_processor._build_rig``) plus a small torso shear, used
  only by states that actually move limbs (WALK, JUMP, PANIC). ``None``
  from :meth:`AnimationEngine.limb_pose` means "no rig needed this
  state" - the caller just draws the plain static image.
* ``Transform`` - a global offset/rotation/scale/opacity applied to the
  whole composed sprite (bob, lean, squash, the lie-down tilt for SLEEP,
  the arc for JUMP, the shake for PANIC). This is intentionally the same
  kind of transform for every state so ``pet_window`` never needs to
  know which state it's drawing.

Nothing here touches Qt, files, or system state - it's pure functions of
(state, elapsed-seconds-in-state), which keeps animation decoupled from
behavior and rendering per the app's layering rule.
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
    """A single frame's whole-sprite transform, applied around its center
    (or, for SLEEP, around a point near its base - see ``pivot_at_base``)."""

    offset_x: float = 0.0
    offset_y: float = 0.0
    rotation_deg: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    opacity: float = 1.0
    facing_left: bool = False
    pivot_at_base: bool = False  # True: rotate around bottom-center instead of the middle


@dataclass
class LimbPose:
    """Per-leg swing angles (degrees) plus a subtle torso shear, shared
    pivot point assumed (see RigAssets.pivot_x/pivot_y)."""

    leg_a_deg: float = 0.0
    leg_b_deg: float = 0.0
    torso_shear: float = 0.0  # implies counter-swinging arms without a real arm cutout


# Tuning constants - kept as module constants rather than magic numbers
# scattered through the functions below, so a future "make it bouncier"
# request is a one-line change.
WALK_STRIDE_HZ = 1.8         # full leg swings per second while walking
WALK_LEG_SWING_DEG = 22.0
WALK_TORSO_SHEAR = 0.05
WALK_BOB_PX = 5.0
JUMP_DURATION = 0.55
JUMP_HEIGHT_PX = 62.0
JUMP_TUCK_DEG = 30.0
PANIC_STRIDE_HZ = 5.0
PANIC_LEG_SWING_DEG = 14.0
TURN_DURATION = 0.22


class AnimationEngine:
    def __init__(self, fps: int = 16) -> None:
        self.fps = fps

    # -- global (whole-sprite) transform ----------------------------------

    def compute(self, state: PetState, elapsed: float, facing_left: bool) -> Transform:
        handler = getattr(self, f"_{state.name.lower()}", self._idle)
        transform = handler(elapsed)
        transform.facing_left = facing_left
        return transform

    # -- per-limb pose, or None if this state doesn't move limbs -----------

    def limb_pose(self, state: PetState, elapsed: float) -> LimbPose | None:
        if state == PetState.WALK:
            return self._walk_limbs(elapsed)
        if state == PetState.JUMP:
            return self._jump_limbs(elapsed)
        if state == PetState.PANIC:
            return self._panic_limbs(elapsed)
        return None

    # -- limb poses ------------------------------------------------------

    def _walk_limbs(self, t: float) -> LimbPose:
        phase = t * WALK_STRIDE_HZ * 2 * math.pi
        a = math.sin(phase) * WALK_LEG_SWING_DEG
        b = math.sin(phase + math.pi) * WALK_LEG_SWING_DEG
        shear = math.sin(phase) * WALK_TORSO_SHEAR
        return LimbPose(leg_a_deg=a, leg_b_deg=b, torso_shear=shear)

    def _jump_limbs(self, t: float) -> LimbPose:
        progress = min(t / JUMP_DURATION, 1.0)
        # Both legs tuck up together (like knees bending for the jump),
        # peaking mid-air, and extend again for landing.
        tuck = math.sin(progress * math.pi) * JUMP_TUCK_DEG
        return LimbPose(leg_a_deg=tuck, leg_b_deg=tuck, torso_shear=0.0)

    def _panic_limbs(self, t: float) -> LimbPose:
        phase = t * PANIC_STRIDE_HZ * 2 * math.pi
        a = math.sin(phase) * PANIC_LEG_SWING_DEG
        b = math.sin(phase + math.pi) * PANIC_LEG_SWING_DEG
        return LimbPose(leg_a_deg=a, leg_b_deg=b, torso_shear=math.sin(phase) * 0.08)

    # -- global transforms -------------------------------------------------

    def _idle(self, t: float) -> Transform:
        bob = math.sin(t * 2.0) * 2.0
        return Transform(offset_y=bob, scale_y=1.0 + math.sin(t * 2.0) * 0.01)

    def _walk(self, t: float) -> Transform:
        # Legs now animate themselves (see _walk_limbs); the whole-body
        # transform just adds the hip bob - two bounces per stride, since
        # the body dips slightly on every footfall (left AND right).
        phase = t * WALK_STRIDE_HZ * 2 * math.pi
        bob = -abs(math.sin(phase)) * WALK_BOB_PX
        lean = math.sin(phase) * 1.5
        return Transform(offset_y=bob, rotation_deg=lean)

    def _jump(self, t: float) -> Transform:
        progress = min(t / JUMP_DURATION, 1.0)
        # eased parabola: fast takeoff, hang at the top, fast landing
        height = -JUMP_HEIGHT_PX * (4 * progress * (1 - progress))
        stretch = 1.0 + 0.12 * math.sin(progress * math.pi)
        return Transform(offset_y=height, scale_x=1.0 / stretch, scale_y=stretch)

    def _fall(self, t: float) -> Transform:
        drop = min(t * t * 300.0, 200.0)
        return Transform(offset_y=drop, scale_y=1.08, scale_x=0.94)

    def _sleep(self, t: float) -> Transform:
        # Lie the character down on its side near the ground, rotating
        # around the base rather than the center so it doesn't float.
        settle = min(t / 0.35, 1.0)  # ease into the lying pose
        angle = -82.0 * settle
        breathe = math.sin(t * 1.3) * 1.2
        return Transform(rotation_deg=angle, offset_y=breathe, opacity=0.95, pivot_at_base=True)

    def _notice(self, t: float) -> Transform:
        wobble = math.sin(t * 8.0) * 4.0 if t < 0.6 else 0.0
        return Transform(rotation_deg=wobble)

    def _excited(self, t: float) -> Transform:
        bounce = abs(math.sin(t * 10.0)) * -10.0
        wiggle = math.sin(t * 10.0) * 6.0
        return Transform(offset_y=bounce, rotation_deg=wiggle)

    def _panic(self, t: float) -> Transform:
        shake = math.sin(t * 25.0) * 4.0
        bob = abs(math.sin(t * PANIC_STRIDE_HZ * 2 * math.pi)) * -5.0
        return Transform(offset_x=shake, offset_y=bob)

    def _turn(self, t: float) -> Transform:
        progress = min(t / TURN_DURATION, 1.0)
        squeeze = 1.0 - 0.6 * math.sin(progress * math.pi)
        return Transform(scale_x=max(0.15, squeeze))
