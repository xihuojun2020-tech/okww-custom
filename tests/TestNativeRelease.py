"""Paired release fixtures; no live source, NAS, GPU or game operations."""

from contextlib import contextmanager
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from src.update.lan_transport import (CertificatePinError, FileShareClient,
    HttpsPinnedClient, LanTransportError, ReleaseNotPublished, _smb_call)
from src.update.native_release_manifest import (NativeReleaseError, artifacts,
    core_version_key, identity_key, parse_release, release_id, validate_artifacts)
from src.update.native_release_service import (AUTO_UPDATE, AUTO_UPDATE_PRE_RELEASE,
    MANUAL_UPDATE, NativeReleaseService)
from scripts.build_gamepack import write_gamepack_archive

from scripts import publish_native_release as publisher
from scripts import build_native_release as builder


def wheel(path, *, name, version):
    path.parent.mkdir(parents=True, exist_ok=True)
    info = name.replace('-', '_') + '-' + version + '.dist-info/'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(info + 'METADATA',
            f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n')
        archive.writestr(info + 'WHEEL', 'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        archive.writestr('never_import.py', 'raise AssertionError("metadata checks must not import")\n')


def artifact(root, path):
    file = root / path
    return {'path': path, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
            'size': file.stat().st_size}


def make_release(root, *, version='1.97.76', channel='stable', revision=0):
    root.mkdir(parents=True, exist_ok=True)
    identity = dict(version=version, channel=channel, revision=revision)
    core_version = '.'.join(str(int(part)) for part in version.split('.'))
    if channel != 'stable':
        core_version += ('a' if channel == 'alpha' else 'b') + str(revision)
    prefix = 'releases/' + release_id(identity)
    core_path = f'{prefix}/gameframe_runtime-{core_version}-py3-none-any.whl'
    wheel(root / core_path, name='gameframe-runtime', version=core_version)
    dependency_path = f'{prefix}/wheelhouse/demo_dep-20240210-py3-none-any.whl'
    wheel(root / dependency_path, name='demo-dep', version='20240210')
    pack_path = f'{prefix}/native_pack-{version}.zip'
    manifest = {'api_version': 1, 'id': 'native_pack', **identity,
        'required_core_version': core_version, 'title': 'Fixture',
        'entrypoint': 'plugin.py:Package', 'license': 'AGPL-3.0-or-later',
        'platforms': ['windows'], 'execution': 'native', 'tasks': []}
    write_gamepack_archive({'manifest.json': json.dumps(manifest).encode(),
        'plugin.py': b'raise AssertionError("Never import this fixture")\n',
        'requirements.txt': b'demo-dep==20240210\n',
        'requirements-management.txt': b'demo-dep==20240210\n'}, root / pack_path, 'native_pack')
    bundle = {'schema_version': 2, 'package_id': 'native_pack', **identity,
        'published_at': '2026-10-11T00:00:00Z',
        'core': {'version': core_version, **artifact(root, core_path)},
        'gamepack': {'package_id': 'native_pack', **identity,
            'required_core_version': core_version, **artifact(root, pack_path)},
        'wheels': [artifact(root, dependency_path)]}
    return bundle


class FakeTransport:
    def __init__(self):
        self.resources, self.calls = {}, []

    def register(self, source_root, channel_root, bundle):
        base = source_root + '/' + bundle['channel'] + '/'
        self.resources[base + 'latest.json'] = json.dumps(bundle).encode()
        for item in artifacts(bundle):
            self.resources[base + item['path']] = channel_root / item['path']

    def get_bytes(self, source, **kwargs):
        self.calls.append(source)
        value = self.resources.get(source, ReleaseNotPublished('fixture missing'))
        if isinstance(value, Exception):
            raise value
        return value

    def download(self, source, destination, **kwargs):
        self.calls.append(source)
        value = self.resources.get(source, ReleaseNotPublished('fixture missing'))
        if isinstance(value, Exception):
            raise value
        return FileShareClient._download_local(value, destination, **kwargs)


@contextmanager
def fixture_lease(*args, **kwargs):
    yield


class TestNativeRelease(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source_root = 'https://offline.invalid/GameFrame-Packages/native_pack'
        self.transport = FakeTransport()
        self.service = NativeReleaseService(package_id='native_pack', data_dir=self.root / 'data',
            source_root=self.source_root, certificate_sha256='a' * 64, transport=self.transport)
        self.current = {'version': '1.97.75', 'channel': 'stable', 'revision': 0}

    def register(self, **changes):
        channel = changes.get('channel', 'stable')
        root = self.root / 'source' / channel
        bundle = make_release(root, **changes)
        self.transport.register(self.source_root, root, bundle)
        return bundle, root

    def test_offline_bundle_builder_preserves_artifacts_and_refuses_output_replacement(self):
        bundle, root = self.register()
        output = self.root / 'assembled'
        record = builder.build(root / bundle['core']['path'], root / bundle['gamepack']['path'],
                               (root / bundle['wheels'][0]['path']).parent, output,
                               published_at=bundle['published_at'])
        built = parse_release(record.read_bytes())
        self.assertEqual(built, bundle)
        validate_artifacts(built, output)
        with self.assertRaises(FileExistsError):
            builder.build(root / bundle['core']['path'], root / bundle['gamepack']['path'],
                          (root / bundle['wheels'][0]['path']).parent, output)

    def test_paired_identity_subset_normalization_and_container_verification(self):
        bundle, root = self.register(version='1.04.02')
        self.assertEqual(bundle['core']['version'], '1.4.2')
        parsed = parse_release(json.dumps(bundle).encode())
        self.assertEqual(parsed, bundle)
        self.assertIsNone(validate_artifacts(parsed, root))
        for version in ('1.97', '1.97.76rc1', '1.97.76.dev1', '1.97.76+local', '1!1.97.76', '1.97.76b0'):
            with self.subTest(version=version), self.assertRaises(NativeReleaseError):
                core_version_key(version)

    def test_schema_rejects_wrong_pairing_types_paths_and_core_requirement(self):
        bundle, _ = self.register()
        mutations = [lambda b: b.update(extra=1), lambda b: b.update(schema_version=True),
            lambda b: b['gamepack'].update(revision=True),
            lambda b: b['gamepack'].update(package_id='other'),
            lambda b: b['gamepack'].update(required_core_version='1.97.77'),
            lambda b: b['core'].update(version='1.97.76b1'),
            lambda b: b['core'].update(path='../core.whl'),
            lambda b: b['core'].update(path='releases/v1.97.76/NUL.whl'),
            lambda b: b['core'].update(path='releases/v1.97.75/core.whl'),
            lambda b: b['core'].update(path='https://foreign.invalid/core.whl'),
            lambda b: b['core'].update(size=True),
            lambda b: b.update(channel='beta', revision=0),
            lambda b: b.update(wheels=[copy.deepcopy(b['wheels'][0]), copy.deepcopy(b['wheels'][0])])]
        for mutation in mutations:
            candidate = copy.deepcopy(bundle)
            mutation(candidate)
            with self.subTest(mutation=mutation), self.assertRaises(NativeReleaseError):
                parse_release(json.dumps(candidate).encode())

    def test_three_policies_explicit_manual_prerelease_order_and_no_downgrade(self):
        self.assertEqual(self.service.check(self.current, MANUAL_UPDATE).status, 'manual')
        self.assertEqual(self.transport.calls, [])
        stable, _ = self.register()
        beta, _ = self.register(version='1.97.77', channel='beta', revision=2)
        alpha, _ = self.register(version='1.97.77', channel='alpha', revision=3)
        self.assertEqual(self.service.check(self.current).release, stable)
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(self.service.check(self.current, AUTO_UPDATE_PRE_RELEASE).release, beta)
        self.assertEqual(self.service.check(self.current, MANUAL_UPDATE, automatic=False).release, beta)
        self.assertGreater(identity_key(beta), identity_key(alpha))
        current = dict(version='1.97.77', channel='beta', revision=2)
        self.assertEqual(self.service.check(current, AUTO_UPDATE).status, 'up_to_date')
        final = dict(version='1.97.77', channel='stable', revision=0)
        self.assertGreater(identity_key(final), identity_key(beta))
        self.assertGreater(identity_key(dict(version='1.97.78', channel='alpha', revision=1)), identity_key(final))

    def test_missing_latest_is_typed_but_permission_pin_and_artifact_errors_fail(self):
        missing = self.service.check(self.current, AUTO_UPDATE_PRE_RELEASE)
        self.assertEqual(missing.status, 'no_release')
        self.assertEqual(missing.unpublished_channels, ('stable', 'beta', 'alpha'))
        bundle, _ = self.register()
        found = self.service.check(self.current, AUTO_UPDATE_PRE_RELEASE)
        self.assertEqual(found.release, bundle)
        self.assertEqual(found.unpublished_channels, ('beta', 'alpha'))
        beta_url = self.source_root + '/beta/latest.json'
        for failure in (PermissionError('denied'), CertificatePinError('pin failed'), LanTransportError('offline')):
            self.transport.resources[beta_url] = failure
            with self.subTest(failure=failure), self.assertRaises(type(failure)):
                self.service.check(self.current, AUTO_UPDATE_PRE_RELEASE)
        del self.transport.resources[self.source_root + '/stable/' + bundle['core']['path']]
        with self.assertRaises(ReleaseNotPublished):
            self.service.download(bundle)
        self.assertEqual(list((self.root / 'data/configs/native-release-staging').iterdir()), [])

    def test_verified_download_keeps_exact_bundle_and_local_artifact_root(self):
        bundle, root = self.register()
        verified = self.service.download(self.service.check(self.current).release)
        self.assertEqual(verified.bundle, bundle)
        self.assertTrue(verified.artifact_root.is_relative_to(self.root / 'data'))
        for item in artifacts(bundle):
            self.assertEqual((verified.artifact_root / item['path']).read_bytes(), (root / item['path']).read_bytes())
        validate_artifacts(verified.bundle, verified.artifact_root)

    def test_corrupt_hash_index_and_core_metadata_rejected_before_verified_handoff(self):
        bundle, root = self.register()
        core = root / bundle['core']['path']
        original = core.read_bytes()
        core.write_bytes(b'corrupt')
        with self.assertRaises(NativeReleaseError):
            validate_artifacts(bundle, root)
        core.write_bytes(original)
        wheel(core, name='other', version=bundle['core']['version'])
        bundle['core'].update(artifact(root, bundle['core']['path']))
        with self.assertRaises(NativeReleaseError):
            validate_artifacts(bundle, root)
        wheel(core, name='gameframe-runtime', version=bundle['core']['version'])
        bundle['core'].update(artifact(root, bundle['core']['path']))
        pack = root / bundle['gamepack']['path']
        with zipfile.ZipFile(pack) as archive:
            content = {name: archive.read(name) for name in archive.namelist()}
        content['native_pack/plugin.py'] = b'changed without index\n'
        with zipfile.ZipFile(pack, 'w') as archive:
            for name, value in content.items():
                archive.writestr(name, value)
        bundle['gamepack'].update(artifact(root, bundle['gamepack']['path']))
        with self.assertRaises(ValueError):
            validate_artifacts(bundle, root)

    def test_source_boundaries_and_only_current_nas_alias(self):
        service = NativeReleaseService(package_id='native_pack', data_dir=self.root,
            source_root=r'\\192.168.3.172\羲火君 共享给我\AI诊断\GameFrame-Packages\native_pack', transport=self.transport)
        self.assertTrue(service.source_root.startswith(r'\\192.168.3.173'))
        service.check(self.current)
        self.assertTrue(all('192.168.3.172' not in source for source in self.transport.calls))
        for source in ('http://offline.invalid/root', 'https://user:pass@offline.invalid/root',
                       'https://offline.invalid/root?secret=1', r'\\server\share\..\elsewhere'):
            with self.subTest(source=source), self.assertRaises((NativeReleaseError, LanTransportError)):
                NativeReleaseService(package_id='native_pack', data_dir=self.root,
                    source_root=source, certificate_sha256='a' * 64, transport=self.transport)

    def test_publisher_verifies_everything_before_atomic_latest_and_rejects_mutation(self):
        bundle, root = self.register()
        destination = self.root / 'published'
        seen = []
        original = publisher.os.replace
        def replace(source, target):
            seen.append(Path(target).name)
            if Path(target).name == 'latest.json':
                validate_artifacts(bundle, destination / 'native_pack/stable')
            return original(source, target)
        with patch.object(publisher.os, 'replace', replace):
            latest = publisher.publish(bundle, root, destination, lease=fixture_lease)
        self.assertEqual(seen[-1], 'latest.json')
        before = latest.read_bytes()
        self.assertEqual(parse_release(before), bundle)
        self.assertEqual(publisher.publish(bundle, root, destination, lease=fixture_lease), latest)
        mutated = copy.deepcopy(bundle)
        mutated['published_at'] = '2026-10-11T01:00:00Z'
        with self.assertRaises(NativeReleaseError):
            publisher.publish(mutated, root, destination, lease=fixture_lease)
        self.assertEqual(latest.read_bytes(), before)
        invalid = copy.deepcopy(bundle)
        invalid['core']['sha256'] = '0' * 64
        untouched = self.root / 'untouched'
        with self.assertRaises(NativeReleaseError):
            publisher.publish(invalid, root, untouched, lease=fixture_lease)
        self.assertFalse(untouched.exists())

    def test_publish_readback_failure_does_not_replace_latest(self):
        bundle, root = self.register()
        destination = self.root / 'published'
        latest = publisher.publish(bundle, root, destination, lease=fixture_lease)
        before = latest.read_bytes()
        newer = make_release(self.root / 'newer', version='1.97.77')
        original = publisher.validate_artifacts
        def validate(value, path):
            if Path(path).is_relative_to(destination):
                raise NativeReleaseError('fixture readback failure')
            return original(value, path)
        with patch.object(publisher, 'validate_artifacts', validate), self.assertRaises(NativeReleaseError):
            publisher.publish(newer, self.root / 'newer', destination, lease=fixture_lease)
        self.assertEqual(latest.read_bytes(), before)

    def test_transport_not_found_is_distinct_from_http_permission_and_smb_failure(self):
        with self.assertRaises(ReleaseNotPublished):
            FileShareClient._read_local(self.root / 'missing.json', max_bytes=1024)
        with patch.object(Path, 'stat', side_effect=PermissionError('denied')):
            with self.assertRaises(LanTransportError) as result:
                FileShareClient._read_local(self.root / 'denied.json', max_bytes=1024)
            self.assertNotIsInstance(result.exception, ReleaseNotPublished)
        from types import SimpleNamespace
        client = HttpsPinnedClient('a' * 64)
        for status, expected in ((404, ReleaseNotPublished), (403, LanTransportError), (500, LanTransportError)):
            connection = SimpleNamespace(request=lambda *a, **k: None,
                getresponse=lambda: SimpleNamespace(status=status), close=lambda: None)
            with patch.object(client, '_connection', return_value=connection):
                with self.subTest(status=status), self.assertRaises(expected) as result:
                    client._stream(self.source_root, io.BytesIO(), max_bytes=1024, deadline_seconds=1)
                if status != 404:
                    self.assertNotIsInstance(result.exception, ReleaseNotPublished)
        for kind, code, expected in (('FileNotFoundError', 2, ReleaseNotPublished),
                                    ('PermissionError', 5, LanTransportError),
                                    ('OSError', 53, LanTransportError)):
            output = SimpleNamespace(returncode=2, stdout=json.dumps(
                dict(error='fixture', error_type=kind, error_code=code)).encode())
            with patch('src.update.lan_transport.subprocess.run', return_value=output):
                with self.subTest(kind=kind), self.assertRaises(expected) as result:
                    _smb_call('read', {}, 1)
                if code != 2:
                    self.assertNotIsInstance(result.exception, ReleaseNotPublished)


if __name__ == '__main__':
    unittest.main()
