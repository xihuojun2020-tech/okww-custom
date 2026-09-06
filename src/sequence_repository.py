"""Standalone PC sequence management and immutable run snapshots."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .account_identity import AccountIdentityError, resolve_profile_identity, resolve_profile_short_names
from .account_repository import AccountRepository, ProfileRevisionConflict


class SequenceRepositoryError(RuntimeError):
    pass


class SequenceReferenceError(SequenceRepositoryError):
    pass


class SequenceDeletionBlocked(SequenceReferenceError):
    pass


@dataclass(frozen=True)
class SequenceEditScope:
    sequence_id: str
    base_revision: str | int


@dataclass(frozen=True)
class SequenceDraft:
    sequence_id: str
    revision: str | int
    profile_ids: tuple[str, ...] = ()
    enabled: bool = True

    @property
    def scope(self) -> SequenceEditScope:
        return SequenceEditScope(self.sequence_id, self.revision)


@dataclass(frozen=True)
class SequenceDiff:
    sequence_id: str
    before: tuple[str, ...]
    after: tuple[str, ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]
    reordered: bool


@dataclass(frozen=True)
class SequenceRunSnapshot:
    sequence_id: str
    revision: str | int
    profile_ids: tuple[str, ...]
    profiles: tuple[Mapping[str, Any], ...]
    run_id: str
    identity_profiles: Mapping[str, Any] = field(default_factory=dict)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in copy.deepcopy(dict(value)).items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return copy.deepcopy(value)


def thaw_snapshot(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: thaw_snapshot(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw_snapshot(item) for item in value]
    return copy.deepcopy(value)


class SequenceRepository:
    def __init__(self, repository: Any):
        self.repository = repository

    def load(self, sequence_id: str) -> SequenceDraft:
        record = self.repository.load_sequence(sequence_id)
        return SequenceDraft(record.sequence_id, record.revision, tuple(record.profile_ids),
                             bool(record.metadata.get("enabled", True)))

    load_sequence = load

    def list(self) -> tuple[SequenceDraft, ...]:
        return tuple(self.load(name) for name in self.repository.list_sequence_ids())

    list_sequences = list

    def _profiles(self) -> dict[str, Any]:
        return {record.profile_id: record for record in self.repository.list_profiles()}

    def _normalize(self, members: Sequence[Any], profiles=None) -> tuple[str, ...]:
        if isinstance(members, (str, bytes)):
            raise SequenceReferenceError("序列成员必须是列表")
        profiles = self._profiles() if profiles is None else profiles
        identities = {profile_id: {**dict(record.account), "task_config": dict(record.tasks)}
                      for profile_id, record in profiles.items()}
        result: list[str] = []
        for member in members:
            value = str(member)
            profile_id = value if value in profiles else None
            if profile_id is None:
                try:
                    profile_id = resolve_profile_identity(value, identities)
                except AccountIdentityError as exc:
                    raise SequenceReferenceError(str(exc)) from exc
            if profile_id is None:
                raise SequenceReferenceError("序列引用了未知账号")
            if profile_id in result:
                raise SequenceReferenceError("序列不能包含重复账号")
            result.append(profile_id)
        return tuple(result)

    def publish(self, scope: SequenceEditScope, draft: SequenceDraft | Mapping[str, Any]) -> SequenceDraft:
        sequence_id = draft.sequence_id if isinstance(draft, SequenceDraft) else str(draft.get("sequence_id", scope.sequence_id))
        if sequence_id != scope.sequence_id:
            raise SequenceRepositoryError("序列草稿跨越了编辑范围")
        members = draft.profile_ids if isinstance(draft, SequenceDraft) else draft.get("profile_ids", ())
        enabled = draft.enabled if isinstance(draft, SequenceDraft) else bool(draft.get("enabled", True))
        normalized = self._normalize(members)
        record = self.repository.publish_sequence(sequence_id, list(normalized),
                                                  expected_revision=scope.base_revision,
                                                  metadata={"enabled": enabled}, source="序列管理页面")
        return SequenceDraft(record.sequence_id, record.revision, tuple(record.profile_ids), enabled)

    def create(self, sequence_id: str, profile_ids: Sequence[Any] = (), *, enabled: bool = True) -> SequenceDraft:
        if sequence_id in self.repository.list_sequence_ids():
            raise SequenceRepositoryError("序列已存在")
        return self.publish(SequenceEditScope(sequence_id, 0),
                            {"sequence_id": sequence_id, "profile_ids": profile_ids, "enabled": enabled})

    def copy(self, sequence_id: str, new_sequence_id: str) -> SequenceDraft:
        current = self.load(sequence_id)
        return self.create(new_sequence_id, current.profile_ids, enabled=current.enabled)

    def rename(self, sequence_id: str, new_sequence_id: str) -> SequenceDraft:
        current = self.load(sequence_id)
        record = self.repository.rename_sequence(sequence_id, new_sequence_id,
                                                 expected_revision=str(current.revision))
        return SequenceDraft(record.sequence_id, record.revision, tuple(record.profile_ids), current.enabled)

    def set_enabled(self, sequence_id: str, enabled: bool) -> SequenceDraft:
        current = self.load(sequence_id)
        return self.publish(current.scope, SequenceDraft(sequence_id, current.revision,
                                                         current.profile_ids, bool(enabled)))

    def delete(self, sequence_id: str) -> SequenceDraft:
        current = self.load(sequence_id)
        self.repository.delete_sequence(sequence_id, expected_revision=str(current.revision))
        return current

    def diff(self, before: SequenceDraft, after: SequenceDraft) -> SequenceDiff:
        left, right = before.profile_ids, after.profile_ids
        return SequenceDiff(before.sequence_id, left, right,
                            tuple(item for item in right if item not in left),
                            tuple(item for item in left if item not in right),
                            set(left) == set(right) and left != right)

    def resolve_short_names(self, short_names: Sequence[Any]) -> list[str]:
        profiles = {record.profile_id: record.account for record in self.repository.list_profiles()}
        try:
            return resolve_profile_short_names(short_names, profiles)
        except AccountIdentityError as exc:
            raise SequenceReferenceError(str(exc)) from exc

    def snapshot_for_profile_ids(self, profile_ids: Sequence[Any], *,
                                 sequence_id: str = "临时序列", revision: str | int = 0,
                                 short_names: bool = False) -> SequenceRunSnapshot:
        records = self._profiles()
        if short_names:
            profile_ids = resolve_profile_short_names(profile_ids, {pid: record.account for pid, record in records.items()})
        return self._snapshot(profile_ids, records, sequence_id, revision)

    def _snapshot(self, profile_ids, records, sequence_id, revision):
        members = self._normalize(profile_ids, records)
        profiles = tuple(_freeze({"profile_id": profile_id, "account": dict(records[profile_id].account),
                                  "tasks": dict(records[profile_id].tasks)}) for profile_id in members)
        identities = _freeze({pid: {**dict(record.account), 'profile_id': pid, 'task_config': dict(record.tasks)}
                              for pid, record in records.items()})
        revision = next(iter(records.values())).revision if records and hasattr(next(iter(records.values())), 'revision') else revision
        return SequenceRunSnapshot(sequence_id, revision, members, profiles, str(uuid.uuid4()), identities)

    def create_run_snapshot(self, sequence_id: str) -> SequenceRunSnapshot:
        if isinstance(self.repository, AccountRepository):
            raw, accounts, sequences = self.repository._load_index()
            if sequence_id not in sequences:
                raise SequenceRepositoryError('序列不存在')
            metadata = raw.get('extensions', {}).get('pc_sequence_settings', {}).get(sequence_id, {})
            if not metadata.get('enabled', True):
                raise SequenceRepositoryError('序列已停用')
            records = {record.profile_id: record for record in self.repository._profile_records(raw, accounts)}
            return self._snapshot(sequences[sequence_id], records, sequence_id, self.repository._revision(raw))
        sequence = self.load(sequence_id)
        if not sequence.enabled:
            raise SequenceRepositoryError("序列已停用")
        return self.snapshot_for_profile_ids(sequence.profile_ids, sequence_id=sequence.sequence_id,
                                             revision=sequence.revision)

    def referencing_sequences(self, profile_id: str) -> tuple[str, ...]:
        return tuple(item.sequence_id for item in self.list() if profile_id in item.profile_ids)

    def ensure_profile_deletable(self, profile_id: str) -> None:
        references = self.referencing_sequences(profile_id)
        if references:
            raise SequenceDeletionBlocked("账号仍被序列引用：" + ", ".join(references))


__all__ = ["SequenceDeletionBlocked", "SequenceDiff", "SequenceDraft", "SequenceEditScope",
           "SequenceReferenceError", "SequenceRepository", "SequenceRepositoryError", "SequenceRunSnapshot"]
