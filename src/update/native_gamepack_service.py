# SPDX-License-Identifier: AGPL-3.0-or-later
"""Existing release transport with the independent gamepack distribution contract."""

import hashlib
import tempfile
from pathlib import Path

from gameframe.packages import PackageManifest, install_archive
from src.runtime.nas_location import DEFAULT_TARGET
from src.update.dependency_compatibility import dependency_lines
from src.update.lan_manifest import LanRelease
from src.update.lan_service import LanUpdateError, LanUpdateService
from src.update.package_validation import UpdatePackageError


class NativeGamePackUpdateService(LanUpdateService):
    def __init__(self, config_path, *, package_root, data_dir, transport=None):
        self.manifest = PackageManifest.read(package_root)
        self.data_dir = Path(data_dir).resolve()
        source = DEFAULT_TARGET + rf'\GameFrame-Packages\{self.manifest.id}\stable\latest.json'
        super().__init__(config_path, transport, default_manifest=source)

    def _read_release(self, data):
        # Filename derives from the selected package, never from a remote path.
        return LanRelease.from_bytes(data, expected_channel=self.config.channel,
                                     package_id=self.manifest.id)

    def _validate_archive(self, archive, release):
        archive = Path(archive)
        if archive.stat().st_size != release.size:
            raise UpdatePackageError('游戏包长度与发布清单不一致')
        with archive.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != release.sha256:
            raise UpdatePackageError('游戏包SHA256与发布清单不一致')
        with tempfile.TemporaryDirectory() as directory:
            incoming = install_archive(archive, Path(directory) / 'packages')
            if not (incoming.root / 'files.json').is_file():
                raise LanUpdateError('游戏包更新必须包含完整文件索引')
            if incoming.id != self.manifest.id or incoming.version != release.version:
                raise LanUpdateError('游戏包身份或版本与发布清单不一致')
            for name in ('requirements.txt', 'requirements-management.txt'):
                if dependency_lines((incoming.root / name).read_bytes()) != dependency_lines(
                        (self.manifest.root / name).read_bytes()):
                    raise LanUpdateError(f'真实依赖发生变化：{name}；请安装完整依赖环境')

    def download(self, release, install_root=None):
        # Keep staging in user data, outside the code directory being replaced.
        return super().download(release, self.data_dir)

    def create_apply_request(self, release, archive):
        self._validate_archive(archive, release)
        return {'event': 'gamepack-update-ready', 'archive': str(Path(archive).resolve()),
                'package_id': self.manifest.id, 'current_version': self.manifest.version,
                'target_version': release.version, 'sha256': release.sha256, 'size': release.size}
