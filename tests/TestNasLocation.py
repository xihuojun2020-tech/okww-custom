import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from unittest.mock import Mock, patch
from src.runtime.nas_location import candidates, DEFAULT_TARGET
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

    def test_diagnostic_upload_and_probe_try_second_alias(self):
        from src.runtime.diagnostic_uploader import bounded_upload,bounded_probe
        with patch('src.runtime.diagnostic_uploader._bounded_upload_one',side_effect=[OSError('offline'),None]) as upload:
            bounded_upload('batch',DEFAULT_TARGET,30)
            self.assertIn('192.168.3.173',upload.call_args.args[1])
            self.assertEqual(upload.call_args.args[2],15)
        with patch('src.runtime.diagnostic_uploader._bounded_probe_one',side_effect=[OSError('offline'),{'status':'passed'}]):
            self.assertIn('192.168.3.173',bounded_probe(DEFAULT_TARGET)['target'])

    def test_known_old_share_migrates_but_custom_source_is_preserved(self):
        old = r'\\192.168.3.161\xihuojun 共享给我\AI诊断\stable\latest.json'
        values = candidates(old)
        self.assertEqual(values[0],DEFAULT_TARGET+r'\stable\latest.json')
        self.assertIn('192.168.3.173',values[1])
        for custom in ('https://custom/source',r'\\192.168.3.172\custom\latest.json'):
            self.assertEqual(candidates(custom),(custom,))

    def test_fallback_source_pinned_for_package_download(self):
        transport=Mock()
        transport.get_bytes.side_effect=[LanTransportError('offline'),release_bytes()]
        with tempfile.TemporaryDirectory() as directory:
            service=LanUpdateService(Path(directory)/'missing.json',transport)
            release=service.check('1.00.00').release
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
