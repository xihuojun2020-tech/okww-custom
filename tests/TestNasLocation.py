import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from unittest.mock import Mock, patch
from src.runtime.nas_location import candidates, credential_shares, DEFAULT_TARGET
from src.update.lan_service import LanUpdateService
from src.update.lan_transport import LanTransportError
from tests.TestLanUpdateService import release_bytes


class TestNasLocation(unittest.TestCase):
    def test_unresponsive_smb_worker_is_bounded(self):
        import subprocess
        from src.update.lan_transport import FileShareClient
        with patch('src.update.lan_transport.subprocess.run',side_effect=subprocess.TimeoutExpired('worker',5)) as run:
            with self.assertRaises(LanTransportError):
                FileShareClient.get_bytes(DEFAULT_TARGET+r'\latest.json',max_bytes=1024,deadline_seconds=5)
            self.assertEqual(run.call_args.kwargs['timeout'],5)

    def test_diagnostic_upload_and_probe_use_only_173_with_full_budget(self):
        from src.runtime.diagnostic_uploader import bounded_upload,bounded_probe
        old = DEFAULT_TARGET.replace('.173', '.172')
        with patch('src.runtime.diagnostic_uploader._bounded_upload_one') as upload:
            bounded_upload('batch',old,30)
            upload.assert_called_once_with('batch', DEFAULT_TARGET, 30)
        with patch('src.runtime.diagnostic_uploader._bounded_probe_one',return_value={'status':'passed'}) as probe:
            self.assertIn('192.168.3.173',bounded_probe(DEFAULT_TARGET)['target'])
            self.assertEqual(probe.call_count, 1)
        with patch('src.runtime.diagnostic_uploader._bounded_upload_one',side_effect=OSError('offline')) as upload:
            with self.assertRaises(OSError):
                bounded_upload('batch',old,30)
            self.assertEqual(upload.call_count, 1)

    def test_known_old_share_migrates_but_custom_source_is_preserved(self):
        old = r'\\192.168.3.161\xihuojun 共享给我\AI诊断\stable\latest.json'
        values = candidates(old)
        self.assertEqual(values[0],DEFAULT_TARGET+r'\stable\latest.json')
        self.assertEqual(len(values), 1)
        for host in ('172', '161', '170', '173'):
            self.assertEqual(candidates(old.replace('.161', '.' + host)), values)
        self.assertIn(r'\\192.168.3.172\羲火君 共享给我',
                      credential_shares(r'\\192.168.3.173\羲火君 共享给我'))
        for custom in ('https://custom/source',r'\\192.168.3.172\custom\latest.json'):
            self.assertEqual(candidates(custom),(custom,))

    def test_migrated_source_pinned_for_package_download(self):
        transport=Mock()
        transport.get_bytes.return_value=release_bytes()
        with tempfile.TemporaryDirectory() as directory:
            import json
            config_path = Path(directory)/'lan_update.json'
            config_path.write_text(json.dumps(dict(enabled=True,
                manifest_url=DEFAULT_TARGET.replace('.173', '.172')+r'\OKWW-Updates\stable\latest.json',
                certificate_sha256='', ca_file='', channel='stable')), encoding='utf-8')
            service=LanUpdateService(config_path,transport)
            self.assertIn('192.168.3.173', service.config.manifest_url)
            release=service.check('1.00.00').release
            self.assertEqual(transport.get_bytes.call_count, 1)
            self.assertIn('192.168.3.173',service.manifest_source)
            package = PureWindowsPath(service.manifest_source).parent / release.package
            with patch('src.update.lan_service.validate_package'), patch.object(type(release),'package_path',return_value=package):
                service.download(release,Path(directory))
            self.assertIn('192.168.3.173',transport.download.call_args.args[0])

    def test_bad_manifest_does_not_fall_back(self):
        transport=Mock()
        transport.get_bytes.return_value=b'{}'
        with tempfile.TemporaryDirectory() as directory:
            service=LanUpdateService(Path(directory)/'missing.json',transport)
            with self.assertRaises(ValueError): service.check('1.00.00')
            self.assertEqual(transport.get_bytes.call_count,1)
