"""Typed Qt event shared by account/sequence editors and runtime consumers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AccountChangeEvent:
    """A successfully published account graph change.

    ``revision`` is the repository revision when the operation returns one;
    deletion events may leave it empty because the deleted record no longer
    exists.  IDs are UUID/sequence identifiers, never display labels.
    """

    kind: str
    revision: str = ""
    profile_ids: tuple[str, ...] = ()
    sequence_ids: tuple[str, ...] = ()


__all__ = ["AccountChangeEvent"]
