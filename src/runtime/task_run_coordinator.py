"""Explicit task lifecycle and stop propagation."""

from __future__ import annotations

from enum import Enum
from typing import Any

from .task_status_model import TaskStatusModel


class TaskRunState(str, Enum):
    IDLE = "idle"
    PREFLIGHT = "preflight"
    READY = "ready"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class TaskRunCoordinator:
    def __init__(self):
        self.state = TaskRunState.IDLE
        self.snapshot: Any | None = None
        self.status = TaskStatusModel()

    def start(self, snapshot: Any) -> TaskStatusModel:
        if self.state not in {TaskRunState.IDLE, TaskRunState.STOPPED, TaskRunState.FAILED}:
            raise RuntimeError("任务已经在运行")
        self.snapshot = snapshot
        self.state = TaskRunState.PREFLIGHT
        self.status = TaskStatusModel("preflight", getattr(snapshot, "profile_ids", ())[0]
                                      if getattr(snapshot, "profile_ids", ()) else "",
                                      str(getattr(snapshot, "sequence_id", "")),
                                      str(getattr(snapshot, "revision", "")),
                                      str(getattr(snapshot, "run_id", "")))
        self.state = TaskRunState.READY
        self.state = TaskRunState.RUNNING
        self.status = TaskStatusModel(TaskRunState.RUNNING.value, self.status.profile_id,
                                      self.status.sequence_id, self.status.revision, self.status.run_id)
        return self.status

    def request_stop(self) -> TaskStatusModel:
        if self.state == TaskRunState.RUNNING:
            self.state = TaskRunState.STOPPING
        if self.state == TaskRunState.STOPPING:
            self.state = TaskRunState.STOPPED
        self.status = TaskStatusModel(self.state.value, self.status.profile_id, self.status.sequence_id,
                                      self.status.revision, self.status.run_id, self.status.error)
        return self.status

    def fail(self, error: str) -> TaskStatusModel:
        self.state = TaskRunState.FAILED
        self.status = TaskStatusModel(self.state.value, self.status.profile_id, self.status.sequence_id,
                                      self.status.revision, self.status.run_id, str(error))
        return self.status


__all__ = ["TaskRunCoordinator", "TaskRunState"]
