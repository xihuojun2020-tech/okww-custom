"""Redacted, UI-friendly task lifecycle status."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskStatusModel:
    phase: str = "idle"
    profile_id: str = ""
    sequence_id: str = ""
    revision: str = ""
    run_id: str = ""
    error: str = ""


__all__ = ["TaskStatusModel"]
