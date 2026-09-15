"""Decides what the pet should be doing right now.

This is the only module that looks at *all* the inputs (timers, random
chance, system severity, notifications, user clicks) and turns them into
a single :class:`~app.animation.PetState`. Movement and animation just
execute whatever state this engine picks; they never make decisions
themselves, and this engine never touches the GUI or a QPixmap directly.
"""

from __future__ import annotations

import random
import time

from .animation import PetState
from .system_monitor import Severity
from . import utils

logger = utils.get_logger("behavior")

# Minimum seconds between repeats of the same reactive state, so the pet
# doesn't flicker between PANIC/EXCITED/NOTICE on every tick.
_REACTION_COOLDOWN = 4.0
_TURN_DURATION = 0.25
_JUMP_DURATION = 0.6


class BehaviorEngine:
    def __init__(self, behavior_config: dict) -> None:
        self.config = behavior_config
        self.state = PetState.IDLE
        self._state_started_at = time.monotonic()
        self._next_idle_deadline = self._roll_idle_deadline()
        self._last_reaction_at = 0.0
        self._pending_notification = False
        self._severity = Severity.GREEN
        self._user_triggered: str | None = None

    # -- external inputs --------------------------------------------------

    def notify(self) -> None:
        self._pending_notification = True

    def set_severity(self, severity: Severity) -> None:
        self._severity = severity

    def trigger(self, state_name: str) -> None:
        """User-driven reaction, e.g. from a mouse click (see pet_window)."""
        self._user_triggered = state_name

    def update_config(self, behavior_config: dict) -> None:
        self.config = behavior_config

    # -- core decision loop -------------------------------------------------

    def elapsed_in_state(self) -> float:
        return time.monotonic() - self._state_started_at

    def _set_state(self, new_state: PetState) -> None:
        if new_state != self.state:
            self.state = new_state
            self._state_started_at = time.monotonic()

    def _roll_idle_deadline(self) -> float:
        lo = self.config.get("idle_min_seconds", 3)
        hi = max(lo + 1, self.config.get("idle_max_seconds", 15))
        return time.monotonic() + random.uniform(lo, hi)

    def tick(self, hit_edge: bool) -> PetState:
        """Advance the state machine by one tick and return the resulting state."""
        now = time.monotonic()
        elapsed = self.elapsed_in_state()

        # Reactive, highest-priority events first (with a cooldown so they
        # can't spam-trigger every tick).
        if self._pending_notification and now - self._last_reaction_at > _REACTION_COOLDOWN:
            self._pending_notification = False
            self._last_reaction_at = now
            self._set_state(PetState.NOTICE)
            return self.state

        if self._user_triggered and now - self._last_reaction_at > 0.5:
            requested = self._user_triggered
            self._user_triggered = None
            self._last_reaction_at = now
            try:
                self._set_state(PetState[requested])
            except KeyError:
                logger.warning("Unknown user-triggered state: %s", requested)
            return self.state

        if self._severity == Severity.RED and now - self._last_reaction_at > _REACTION_COOLDOWN:
            self._last_reaction_at = now
            self._set_state(PetState.PANIC)
            return self.state

        if self._severity == Severity.YELLOW and self.state == PetState.IDLE and now - self._last_reaction_at > _REACTION_COOLDOWN:
            self._last_reaction_at = now
            self._set_state(PetState.EXCITED)
            return self.state

        # Let short, self-timing reactions finish naturally.
        if self.state == PetState.NOTICE and elapsed > 2.5:
            self._set_state(PetState.IDLE)
        elif self.state == PetState.EXCITED and elapsed > 2.0:
            self._set_state(PetState.IDLE)
        elif self.state == PetState.PANIC and elapsed > 3.0:
            self._set_state(PetState.IDLE)
        elif self.state == PetState.TURN and elapsed > _TURN_DURATION:
            self._set_state(PetState.WALK)
        elif self.state == PetState.JUMP and elapsed > _JUMP_DURATION:
            self._set_state(PetState.WALK if hit_edge is False else PetState.IDLE)

        if hit_edge and self.state == PetState.WALK:
            self._set_state(PetState.TURN)
            return self.state

        if self.state in (PetState.WALK,):
            jump_p = self.config.get("jump_probability", 0.02)
            if random.random() < jump_p:
                self._set_state(PetState.JUMP)
                return self.state

        if self.state == PetState.IDLE:
            sleep_p = self.config.get("sleep_probability", 0.005)
            if random.random() < sleep_p:
                self._set_state(PetState.SLEEP)
                return self.state
            if now >= self._next_idle_deadline:
                self._next_idle_deadline = self._roll_idle_deadline()
                self._set_state(PetState.WALK)
                return self.state
            random_action_p = self.config.get("random_action_probability", 0.01)
            if random.random() < random_action_p:
                self._set_state(PetState.JUMP)
                return self.state

        if self.state == PetState.SLEEP:
            # Wake up after a while, proportional to the idle window.
            if elapsed > self.config.get("idle_max_seconds", 15):
                self._set_state(PetState.IDLE)
                self._next_idle_deadline = self._roll_idle_deadline()

        return self.state
