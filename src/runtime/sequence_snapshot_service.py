"""Immutable sequence snapshots for one task run."""

from __future__ import annotations

from typing import Any

from ..sequence_repository import SequenceRepository, SequenceRunSnapshot


class SequenceSnapshotService:
    def __init__(self, repository: Any):
        self.repository = repository
        self.sequences = SequenceRepository(repository)

    def create(self, sequence_id: str) -> SequenceRunSnapshot:
        return self.sequences.create_run_snapshot(sequence_id)

    def create_for_profile_ids(self, profile_ids, *, sequence_id: str = "临时序列",
                               revision: str | int = 0, short_names: bool = False) -> SequenceRunSnapshot:
        return self.sequences.snapshot_for_profile_ids(profile_ids, sequence_id=sequence_id,
                                                        revision=revision, short_names=short_names)


__all__ = ["SequenceSnapshotService"]
