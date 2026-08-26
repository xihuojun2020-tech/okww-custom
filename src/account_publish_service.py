"""Crash-safe publication of a complete account configuration snapshot."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .config_integrity import _atomic_write_json_unchecked, atomic_write_json, canonical_json
from .account_repository import ProfileRevisionConflict


_PUBLISH_LOCK = threading.RLock()


@dataclass(frozen=True)
class PublishedRevision:
    revision: str
    bundle_dir: Path
    manifest: Mapping[str, Any]


class PublishState(str, Enum):
    PREPARED = "prepared"
    VERIFIED = "verified"
    ACTIVATED = "activated"
    MIRRORED = "mirrored"


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AccountPublishService:
    """Write a complete bundle then atomically advance the active pointer."""

    def __init__(self, root: os.PathLike | str, *, program_version: str = "development",
                 fail_after_bundle_write: bool = False):
        base = Path(root).resolve()
        self.config_dir = base / "configs" if base.name.casefold() != "configs" else base
        self.root = self.config_dir / "published"
        self.bundles_dir = self.root / "bundles"
        self.active_path = self.root / "active.json"
        self.program_version = str(program_version)
        self.fail_after_bundle_write = bool(fail_after_bundle_write)
        self.publish_state = PublishState.PREPARED

    @staticmethod
    def _master(profiles: Mapping[str, Any], sequences: Mapping[str, list[str]], index: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "config_id": str(index.get("config_id") or "account-profiles"),
            "timezone": str(index.get("timezone") or "Asia/Shanghai"),
            "profiles": copy.deepcopy(dict(profiles)),
            "sequences": copy.deepcopy(dict(sequences)),
            "extensions": copy.deepcopy(dict(index.get("extensions", {})))
            if isinstance(index.get("extensions", {}), Mapping) else {},
        }

    @staticmethod
    def _working(master: Mapping[str, Any]) -> dict[str, Any]:
        profiles = {}
        for profile_id, profile in master.get("profiles", {}).items():
            profile = copy.deepcopy(dict(profile))
            display = str(profile.get("display_name") or profile_id)
            task = profile.pop("task_config", {})
            profile.update(task if isinstance(task, Mapping) else {})
            profiles[display] = profile
        names = {pid: str(profile.get("display_name") or pid)
                 for pid, profile in master.get("profiles", {}).items()}
        return {"profiles": profiles,
                "sequences": {name: [names.get(pid, pid) for pid in members]
                              for name, members in master.get("sequences", {}).items()}}

    def _active_revision(self) -> str:
        if not self.active_path.is_file():
            return ""
        try:
            raw = json.loads(self.active_path.read_text(encoding="utf-8"))
            return str(raw.get("revision") or "")
        except (OSError, UnicodeError, json.JSONDecodeError):
            return ""

    def _write_editable_mirror(self, profiles: Mapping[str, Any], index: Mapping[str, Any],
                               sequences: Mapping[str, list[str]]) -> None:
        """Keep one-JSON-per-account editor files in sync before activation."""
        root = self.config_dir / "accounts"
        profile_dir = root / "profiles"
        profile_dir.mkdir(parents=True, exist_ok=True)
        mirror_index = copy.deepcopy(dict(index))
        mirror_index.setdefault("schema_version", 1)
        mirror_index["profile_ids"] = [str(profile_id) for profile_id in profiles]
        mirror_index["sequences"] = copy.deepcopy(dict(sequences))
        atomic_write_json(root / "index.json", mirror_index)
        atomic_write_json(root / "sequences.json", sequences)
        for profile_id, profile in profiles.items():
            atomic_write_json(profile_dir / f"{profile_id}.json", profile)

    _mirror_projections = _write_editable_mirror

    def publish(self, *, expected_revision: str, profiles: Mapping[str, Any],
                index: Mapping[str, Any], sequences: Mapping[str, list[str]]) -> PublishedRevision:
        with _PUBLISH_LOCK:
            self.publish_state = PublishState.PREPARED
            current = self._active_revision()
            if expected_revision not in ("", None) and str(expected_revision) != current:
                raise ProfileRevisionConflict("已发布账号配置已被其他操作修改")
            master = self._master(profiles, sequences, index)
            working = self._working(master)
            revision = _digest({"master": master, "working": working})
            self.bundles_dir.mkdir(parents=True, exist_ok=True)
            staging = self.bundles_dir / f".tmp-{revision}-{uuid.uuid4().hex[:8]}"
            bundle_dir = self.bundles_dir / revision
            staging.mkdir(parents=True, exist_ok=False)
            try:
                (staging / "profiles").mkdir()
                for profile_id, profile in profiles.items():
                    atomic_write_json(staging / "profiles" / f"{profile_id}.json", profile)
                atomic_write_json(staging / "index.json", index)
                atomic_write_json(staging / "sequences.json", sequences)
                _atomic_write_json_unchecked(staging / "account_master_config.json", master)
                atomic_write_json(staging / "daily_profiles.json", working)
                files = {}
                for path in sorted(staging.rglob("*")):
                    if path.is_file():
                        files[str(path.relative_to(staging)).replace("\\", "/")] = {
                            "sha256": _file_digest(path), "size": path.stat().st_size}
                manifest = {"schema_version": 1, "revision": revision,
                            "program_version": self.program_version,
                            "files": files}
                atomic_write_json(staging / "manifest.json", manifest)
                self.publish_state = PublishState.VERIFIED
                if self.fail_after_bundle_write:
                    raise RuntimeError("forced publication failure")
                if bundle_dir.exists():
                    shutil.rmtree(bundle_dir)
                os.replace(staging, bundle_dir)
                self.publish_state = PublishState.ACTIVATED
                self._mirror_projections(profiles, index, sequences)
                pointer = {"revision": revision, "manifest_sha256": _file_digest(bundle_dir / "manifest.json")}
                atomic_write_json(self.active_path, pointer)
                self.publish_state = PublishState.MIRRORED
                return PublishedRevision(revision, bundle_dir, manifest)
            except Exception:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
                raise

    def load_active(self) -> PublishedRevision:
        if not self.active_path.is_file():
            raise FileNotFoundError("active account bundle is missing")
        pointer = json.loads(self.active_path.read_text(encoding="utf-8"))
        revision = str(pointer.get("revision") or "")
        bundle_dir = self.bundles_dir / revision
        manifest_path = bundle_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("revision") != revision:
            raise ValueError("active bundle revision mismatch")
        if pointer.get("manifest_sha256") != _file_digest(manifest_path):
            raise ValueError("active bundle manifest mismatch")
        for relative, expected in manifest.get("files", {}).items():
            path = bundle_dir / relative
            if not path.is_file() or _file_digest(path) != expected.get("sha256"):
                raise ValueError(f"active bundle file mismatch: {relative}")
        return PublishedRevision(revision, bundle_dir, manifest)

    def recover_incomplete_transactions(self) -> None:
        """Leave the active bundle untouched; incomplete staging is disposable."""
        self.bundles_dir.mkdir(parents=True, exist_ok=True)
        for path in self.bundles_dir.iterdir():
            if path.name.startswith(".tmp-") and path.is_dir():
                shutil.rmtree(path, ignore_errors=True)


__all__ = ["AccountPublishService", "PublishState", "PublishedRevision"]
