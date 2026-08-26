"""Game-level semantic actions; character decisions stay in existing modules."""

from __future__ import annotations

import math
from typing import Any, Mapping

from .control import ControlBoundary, ControlMode
from .protocol import CombatMessage


class GameActions:
    def __init__(self, control: ControlBoundary) -> None:
        self.control = control

    def normal_attack(self) -> CombatMessage:
        return self._action("normal_attack")

    def heavy_attack(self, duration: float) -> CombatMessage:
        return self._action("heavy_attack", {"duration": self._duration(duration)})

    def resonance_skill(self) -> CombatMessage:
        return self._action("resonance_skill")

    def liberation(self) -> CombatMessage:
        return self._action("liberation")

    def echo_skill(self) -> CombatMessage:
        return self._action("echo_skill")

    def dodge(self, direction: tuple[float, float] | list[float] | str) -> CombatMessage:
        return self._action("dodge", {"direction": self._direction(direction)})

    def jump(self) -> CombatMessage:
        return self._action("jump")

    def move(self, vector: tuple[float, float] | list[float], duration: float) -> CombatMessage:
        return self._action("move", {"vector": self._vector(vector), "duration": self._duration(duration)})

    def camera(self, delta: tuple[float, float] | list[float], duration: float) -> CombatMessage:
        return self._action("camera", {"delta": self._vector(delta), "duration": self._duration(duration)})

    def switch_character(self, index: int) -> CombatMessage:
        if isinstance(index, bool) or not isinstance(index, int) or index not in range(3):
            raise ValueError("character index must be 0, 1, or 2")
        return self._action("switch_character", {"index": index})

    def break_action(self) -> CombatMessage:
        return self._action("break_action")

    def release(self, action: str) -> CombatMessage:
        if not isinstance(action, str) or not action.strip():
            raise ValueError("action must be non-empty")
        return self._action("release", {"target": action.strip()})

    def release_all(self) -> bool:
        return self.control.release_all()

    def _action(self, name: str, payload: Mapping[str, Any] | None = None) -> CombatMessage:
        return self.control.submit_action(name, payload, mode=ControlMode.COMBAT)

    @staticmethod
    def _duration(value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("duration must be a number")
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("duration must be finite and positive")
        return value

    @staticmethod
    def _vector(value: tuple[float, float] | list[float]) -> dict[str, float]:
        if not isinstance(value, (tuple, list)) or len(value) != 2:
            raise ValueError("vector must contain exactly two normalized values")
        if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
            raise ValueError("vector values must be numbers")
        vector = tuple(float(item) for item in value)
        if any(not math.isfinite(item) or not -1.0 <= item <= 1.0 for item in vector):
            raise ValueError("vector values must be in [-1, 1]")
        return {"x": vector[0], "y": vector[1]}

    @classmethod
    def _direction(cls, value: tuple[float, float] | list[float] | str) -> dict[str, float]:
        if isinstance(value, str):
            directions = {
                "up": (0.0, -1.0), "down": (0.0, 1.0),
                "left": (-1.0, 0.0), "right": (1.0, 0.0),
            }
            try:
                value = directions[value.strip().lower()]
            except KeyError as exc:
                raise ValueError("direction must be up/down/left/right or a normalized vector") from exc
        return cls._vector(value)
