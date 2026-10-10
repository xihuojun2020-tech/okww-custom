"""Real indexed gamepack download/validation with local transport, no NAS."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from gameframe.packages import install_archive
from scripts.build_gamepack import write_gamepack_archive
from src.update.lan_manifest import LanManifestError
from src.update.lan_service import LanUpdateError
from src.update.lan_transport import FileShareClient
from src.update.native_gamepack_service import NativeGamePackUpdateService
from src.update.package_validation import UpdatePackageError


class LocalReleaseTransport:
    def __init__(self, archive, version):
        self.archive = archive
        self.calls = []
        self.release = {'schema_version': 1, 'channel': 'stable', 'version': version,
            'package': f'releases/v{version}/wuthering_waves_native-{version}.zip',
            'size': archive.stat().st_size, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
            'published_at': '2026-10-11T00:00:00Z'}

    def get_bytes(self, source, **kwargs):
        self.calls.append(source)
        return json.dumps(self.release).encode()

    def download(self, source, destination, **kwargs):
        self.calls.append(source)
        return FileShareClient._download_local(self.archive, destination, **kwargs)


def package(path, version, *, requirements=b'numpy==2.2.6\n', package_id='wuthering_waves_native'):
    manifest = {'api_version': 1, 'id': package_id, 'title': 'test', 'version': version,
        'entrypoint': 'plugin.py:Package', 'license': 'AGPL-3.0-or-later', 'platforms': ['windows'],
        'execution': 'native', 'tasks': [{'id': 'test', 'title': 'test', 'kind': 'one-shot'}]}
    return write_gamepack_archive({'manifest.json': json.dumps(manifest).encode(),
        'plugin.py': b'raise AssertionError("update must not import game code")\n',
        'requirements.txt': requirements, 'requirements-management.txt': b'PySide6==6.9.1\n'},
        path, package_id)


class TestNativeGamePackUpdate(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.current = install_archive(package(self.root / 'old.zip', '1.97.66'), self.root / 'packages')

    def service(self, transport):
        config = self.root / 'data/configs/gamepack-update.json'
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({'enabled': True,
            'manifest_url': 'https://offline.invalid/GameFrame-Packages/wuthering_waves_native/stable/latest.json',
            'certificate_sha256': 'a' * 64, 'ca_file': '', 'channel': 'stable'}), encoding='utf-8')
        return NativeGamePackUpdateService(config,
            package_root=self.current.root, data_dir=self.root / 'data', transport=transport)

    def test_local_verified_download_and_namespace_leave_installed_and_data_intact(self):
        archive = package(self.root / 'new.zip', '1.97.67', requirements=b'# formatting only\n\nnumpy==2.2.6 \n')
        transport = LocalReleaseTransport(archive, '1.97.67')
        default = NativeGamePackUpdateService(self.root / 'missing.json',
            package_root=self.current.root, data_dir=self.root / 'data', transport=transport)
        self.assertIn(r'\GameFrame-Packages\wuthering_waves_native\stable', default.manifest_source)
        service = self.service(transport)
        self.assertEqual(transport.calls, [])
        availability = service.check(self.current.version)
        downloaded = service.download(availability.release)
        request = service.create_apply_request(availability.release, downloaded)
        self.assertEqual(request['event'], 'gamepack-update-ready')
        self.assertEqual(request['current_version'], '1.97.66')
        self.assertTrue(downloaded.is_relative_to(self.root / 'data'))
        self.assertEqual(json.loads((self.current.root / 'manifest.json').read_text())['version'], '1.97.66')
        self.assertNotIn('restart_command', request)
        self.assertTrue(all('GameFrame-Packages' in path for path in transport.calls))

    def test_wrong_legacy_release_filename_is_rejected(self):
        transport = LocalReleaseTransport(package(self.root / 'new.zip', '1.97.67'), '1.97.67')
        transport.release['package'] = 'releases/v1.97.67/okww_update_v1.97.67.zip'
        with self.assertRaises(LanManifestError):
            self.service(transport).check('1.97.66')

    def test_wrong_package_and_changed_dependencies_reject_before_apply_request(self):
        for index, changes in enumerate(({'package_id': 'other'}, {'requirements': b'numpy==2.3.0\n'})):
            transport = LocalReleaseTransport(package(self.root / f'bad-{index}.zip', '1.97.67', **changes), '1.97.67')
            service = self.service(transport)
            release = service.check('1.97.66').release
            with self.assertRaises(LanUpdateError):
                service.download(release)

    def test_outer_sha_failure_rejects_cached_or_mutated_download(self):
        archive = package(self.root / 'new.zip', '1.97.67')
        transport = LocalReleaseTransport(archive, '1.97.67')
        service = self.service(transport)
        release = service.check('1.97.66').release
        downloaded = service.download(release)
        data = bytearray(downloaded.read_bytes())
        data[-1] ^= 1
        downloaded.write_bytes(data)
        with self.assertRaises(UpdatePackageError):
            service.create_apply_request(release, downloaded)

    def test_corrupt_cache_is_downloaded_again(self):
        archive = package(self.root / 'new.zip', '1.97.67')
        transport = LocalReleaseTransport(archive, '1.97.67')
        service = self.service(transport)
        release = service.check('1.97.66').release
        downloaded = service.download(release)
        for damaged in (b'truncated', bytes([archive.read_bytes()[0] ^ 1]) + archive.read_bytes()[1:]):
            downloaded.write_bytes(damaged)
            before = len(transport.calls)
            self.assertEqual(service.download(release), downloaded)
            self.assertEqual(len(transport.calls), before + 1)
            self.assertEqual(downloaded.read_bytes(), archive.read_bytes())


if __name__ == '__main__':
    unittest.main()
