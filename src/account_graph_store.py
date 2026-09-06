"""Canonical runtime boundary for the published account graph."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from .account_publish_service import AccountPublishService, PublishState, PublishedRevision


@dataclass(frozen=True)
class ActiveAccountGraph:
    revision: str
    profiles: Mapping[str, Any]
    index: Mapping[str, Any]
    sequences: Mapping[str, list[str]]
    bundle_dir: Path
    maintenance_errors: tuple[str, ...] = ()


class AccountGraphStore:
    """Load and publish a complete immutable account graph."""

    def __init__(self, root: str | Path, *, publish_service: AccountPublishService | None = None):
        self.service = publish_service or AccountPublishService(root)

    @property
    def active_path(self) -> Path:
        return self.service.active_path

    @property
    def state(self) -> PublishState:
        return self.service.publish_state

    def load_active(self) -> ActiveAccountGraph:
        active: PublishedRevision = self.service.load_active()
        master_path = active.bundle_dir / "account_master_config.json"
        master = json.loads(master_path.read_text(encoding="utf-8"))
        if not isinstance(master, Mapping):
            raise ValueError("active account graph must be an object")
        profiles = master.get("profiles", {})
        sequences = master.get("sequences", {})
        if not isinstance(profiles, Mapping) or not isinstance(sequences, Mapping):
            raise ValueError("active account graph has invalid profiles or sequences")
        index = {key: copy.deepcopy(value) for key, value in master.items()
                 if key not in {"profiles", "sequences"}}
        return ActiveAccountGraph(active.revision, copy.deepcopy(dict(profiles)), index,
                                  copy.deepcopy(dict(sequences)), active.bundle_dir)

    def publish(self, candidate: Mapping[str, Any], *, expected_revision: str = "") -> ActiveAccountGraph:
        if not isinstance(candidate, Mapping):
            raise ValueError("account graph candidate must be an object")
        profiles = candidate.get("profiles", {})
        sequences = candidate.get("sequences", {})
        index = candidate.get("index", candidate.get("metadata", {}))
        if not isinstance(profiles, Mapping) or not isinstance(sequences, Mapping) or not isinstance(index, Mapping):
            raise ValueError("account graph candidate has invalid shape")
        result = self.service.publish(expected_revision=str(expected_revision or ""),
                                      profiles=profiles, index=index, sequences=sequences)
        return replace(self.load_active(), maintenance_errors=result.maintenance_errors)


__all__ = ["AccountGraphStore", "ActiveAccountGraph"]
