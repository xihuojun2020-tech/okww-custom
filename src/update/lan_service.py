from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from .lan_manifest import LanManifestError, LanRelease
from .lan_transport import FileShareClient, HttpsPinnedClient, LanTransportError
from src.runtime.nas_location import DEFAULT_TARGET, candidates
from .package_validation import validate_package

MANIFEST_LIMIT = 65536
DEFAULT_SMB_MANIFEST = DEFAULT_TARGET + r'\OKWW-Updates\stable\latest.json'


class LanUpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class LanUpdateConfig:
    enabled: bool
    manifest_url: str
    certificate_sha256: str
    ca_file: str
    channel: str

    @classmethod
    def load(cls, path: Path) -> "LanUpdateConfig":
        path = Path(path)
        if not path.is_file():
            return cls(True, DEFAULT_SMB_MANIFEST, "", "", "stable")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LanUpdateError("局域网更新配置无效") from exc
        keys = {"enabled", "manifest_url", "certificate_sha256", "ca_file", "channel"}
        if not isinstance(value, dict) or set(value) != keys:
            raise LanUpdateError("局域网更新配置字段无效")
        if type(value["enabled"]) is not bool or not all(isinstance(value[key], str) for key in keys - {"enabled"}):
            raise LanUpdateError("局域网更新配置类型无效")
        if value["channel"] != "stable":
            raise LanUpdateError("首版只支持 stable 通道")
        is_unc = value["manifest_url"].startswith("\\\\")
        is_https = value["manifest_url"].startswith("https://")
        if value["enabled"] and not (is_unc or is_https):
            raise LanUpdateError("更新源必须是 HTTPS 地址或 UNC 共享路径")
        if value["enabled"] and is_https and not re.fullmatch(r"[0-9a-f]{64}", value["certificate_sha256"]):
            raise LanUpdateError("HTTPS 更新需要 NAS 证书指纹")
        migrated = candidates(value["manifest_url"])[0]
        if migrated != value["manifest_url"]:
            from src.runtime.diagnostic_export import atomic_json
            value["manifest_url"] = migrated
            atomic_json(path, value)
        return cls(**value)


@dataclass(frozen=True)
class UpdateAvailability:
    status: Literal["disabled", "up_to_date", "available"]
    release: LanRelease | None
    message: str


class LanUpdateService:
    def __init__(self, config_path: Path, transport=None):
        self.config_path = Path(config_path)
        self.config = LanUpdateConfig.load(self.config_path)
        self.transport = transport
        self.manifest_source = self.config.manifest_url

    def _transport(self):
        if self.transport is None:
            if self.config.manifest_url.startswith("\\\\"):
                self.transport = FileShareClient()
            else:
                ca = Path(self.config.ca_file) if self.config.ca_file else None
                self.transport = HttpsPinnedClient(self.config.certificate_sha256, ca)
        return self.transport

    def check(self, current_version: str) -> UpdateAvailability:
        if not self.config.enabled:
            return UpdateAvailability("disabled", None, "局域网更新未启用")
        for source in candidates(self.config.manifest_url):
            try:
                data = self._transport().get_bytes(source, max_bytes=MANIFEST_LIMIT,
                                                   deadline_seconds=5.0)
                self.manifest_source = source
                break
            except (OSError, LanTransportError):
                if source == candidates(self.config.manifest_url)[-1]:
                    raise
        release = LanRelease.from_bytes(data, expected_channel=self.config.channel)
        if not release.is_newer_than(current_version):
            return UpdateAvailability("up_to_date", None, "当前已是最新版本")
        return UpdateAvailability("available", release, f"发现局域网版本 {release.version}")

    def download(self, release: LanRelease, install_root: Path) -> Path:
        root = Path(install_root).resolve()
        staging = (root / "configs" / "update-staging" / f"v{release.version}").resolve()
        if not staging.is_relative_to(root / "configs" / "update-staging"):
            raise LanUpdateError("更新暂存目录越界")
        archive = staging / Path(release.package).name
        if archive.is_file():
            try:
                validate_package(archive, expected_version=release.version, expected_sha256=release.sha256,
                                 expected_size=release.size)
                return archive
            except (OSError, ValueError):
                archive.unlink(missing_ok=True)
        source = (str(release.package_path(Path(self.manifest_source)))
                  if self.manifest_source.startswith("\\\\")
                  else release.package_url(self.manifest_source))
        self._transport().download(source, archive,
                                   expected_size=release.size, expected_sha256=release.sha256)
        validate_package(archive, expected_version=release.version, expected_sha256=release.sha256,
                         expected_size=release.size)
        return archive

    def create_apply_request(self, release: LanRelease, archive: Path, install_root: Path,
                             restart_command: Sequence[str]) -> Path:
        root, archive = Path(install_root).resolve(), Path(archive).resolve()
        expected_stage = (root / "configs" / "update-staging" / f"v{release.version}").resolve()
        if not archive.is_relative_to(expected_stage) or not root.is_dir() or root.is_symlink():
            raise LanUpdateError("更新请求路径无效")
        validate_package(archive, expected_version=release.version, expected_sha256=release.sha256,
                         expected_size=release.size)
        from config import version as current_version
        request = {
            "schema_version": 1, "from_version": current_version, "to_version": release.version,
            "archive": str(archive), "sha256": release.sha256, "size": release.size,
            "install_root": str(root), "parent_pid": os.getpid(),
            "restart_command": [str(item) for item in restart_command],
        }
        target, pending = expected_stage / "apply-request.json", expected_stage / "apply-request.json.tmp"
        target.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(request, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        with pending.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, target)
        return target
