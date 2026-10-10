# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicit gamepack update actions; application is owned by the launcher."""

import json
from pathlib import Path

from src.gui.LanUpdateCard import LanUpdateCard
from src.update.native_gamepack_service import NativeGamePackUpdateService


class NativeGamePackUpdateCard(LanUpdateCard):
    def __init__(self, *, package_root, data_dir, parent=None):
        from gameframe.packages import PackageManifest
        manifest = PackageManifest.read(package_root)
        super().__init__(Path(data_dir) / 'configs/gamepack-update.json', manifest.version,
                         None, parent)
        self.package_root = Path(package_root)
        self.data_dir = Path(data_dir)
        self.set_description('检查独立游戏包发布源；下载验证后关闭管理窗口，由启动器替换包。游戏不会自动重启。')

    def _check(self):
        self._show_status('正在检查游戏包更新…')

        def work():
            service = NativeGamePackUpdateService(self.config_path,
                package_root=self.package_root, data_dir=self.data_dir)
            return service, service.check(self.current_version)

        def complete(value):
            self.service, availability = value
            self.release = availability.release
            self._show_status(availability.message)
            self.action.setText('下载并更新游戏包' if self.release else '重新检查')

        self.operation.start(work, complete, self._failed, timeout_ms=20000)

    def _download(self):
        release, service = self.release, self.service
        self._show_status('正在下载并验证游戏包…')

        def work():
            archive = service.download(release)
            return service.create_apply_request(release, archive)

        def complete(request):
            self._show_status(f'已验证版本 {release.version}，等待启动器替换游戏包。')
            print(json.dumps(request, ensure_ascii=False), flush=True)
            self.window().close()

        self.operation.start(work, complete, self._failed)
