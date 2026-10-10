"""The small contract shared by game packages and device backends."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

import numpy as np


@dataclass(frozen=True)
class Frame:
    sequence: int
    image: np.ndarray
    captured_ns: int
    timestamp_source: str = 'host-received'


@dataclass(frozen=True)
class Action:
    kind: str
    values: Mapping[str, Any] = field(default_factory=dict)


class Device(Protocol):
    capabilities: frozenset[str]

    def next_frame(self, timeout: float = 1.0) -> Frame | None: ...
    def submit(self, action: Action) -> None: ...
    def release_all(self) -> None: ...
    def close(self) -> None: ...


class Cancelled(Exception):
    """Explicit stop or application exit, rather than an ordinary task error."""


@dataclass
class TaskContext:
    device: Device
    config: dict[str, Any]
    data_dir: Path
    stop: threading.Event
    run_id: str
    events: Any

    def check_stop(self) -> None:
        if self.stop.is_set():
            raise Cancelled('Task stopped')

    def frame(self, timeout: float = 1.0) -> Frame:
        self.check_stop()
        frame = self.device.next_frame(timeout)
        if frame is None:
            raise TimeoutError('No new device frame')
        return frame

    def act(self, kind: str, **values: Any) -> None:
        self.check_stop()
        self.device.submit(Action(kind, values))

    def sleep(self, seconds: float) -> None:
        if self.stop.wait(seconds):
            raise Cancelled('Task stopped')

    def emit(self, kind: str, **values: Any) -> None:
        self.events({'event': kind, 'run_id': self.run_id,
                     'monotonic_ns': time.monotonic_ns(), **values})


class GamePackage(Protocol):
    def run(self, task_id: str, context: TaskContext) -> Mapping[str, Any]: ...
