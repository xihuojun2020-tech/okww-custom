import hashlib
import json
import tempfile
import unittest
import zipfile
import subprocess
import sys
import os
from pathlib import Path
from unittest.mock import patch

from src.update.lan_apply import apply_request, _running, _wait_parent
from src.update.dependency_compatibility import repair_legacy_requirements


class TestLanUpdateApply(unittest.TestCase):
    def test_parent_wait_never_signals_or_terminates_process(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                 creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
        try:
            self.assertTrue(_running(child.pid))
            self.assertFalse(_wait_parent(child.pid, 0.2))
            self.assertIsNone(child.poll())
        finally:
            child.terminate()
            child.wait(timeout=5)
        self.assertFalse(_running(child.pid))

    @patch('src.update.lan_apply.subprocess.Popen')
    def test_bad_archive_persists_failure_without_changing_files(self, popen):
        with tempfile.TemporaryDirectory() as temp:
            root, request = self.fixture(temp)
            data = json.loads(request.read_text())
            data['sha256'] = '0' * 64
            request.write_text(json.dumps(data))
            result = apply_request(request)
            self.assertEqual('failed', result.status)
            self.assertIn('SHA-256', result.message)
            self.assertEqual('failed', json.loads((root / 'configs/update-result.json').read_text())['status'])
            self.assertFalse(request.with_suffix('.ready.json').exists())
            self.assertEqual('old', (root / 'src/example.py').read_text())

    @patch('src.update.lan_apply.subprocess.Popen')
    def test_live_parent_timeout_does_not_restart_or_replace(self, popen):
        with tempfile.TemporaryDirectory() as temp:
            root, request = self.fixture(temp)
            data = json.loads(request.read_text())
            data['parent_pid'] = os.getpid()
            request.write_text(json.dumps(data))
            result = apply_request(request, wait_timeout=0.1)
            self.assertEqual('failed', result.status)
            self.assertIn('未在期限内退出', result.message)
            self.assertEqual('old', (root / 'src/example.py').read_text())
            popen.assert_not_called()

    @patch('src.update.lan_apply.subprocess.Popen', side_effect=OSError('restart blocked'))
    def test_restart_failure_is_recorded(self, popen):
        with tempfile.TemporaryDirectory() as temp:
            root, request = self.fixture(temp)
            result = apply_request(request)
            self.assertEqual('succeeded', result.status)
            self.assertIn('自动重启失败', result.message)
            self.assertIn('restart blocked', (root / 'configs/update-result.json').read_text())

    def fixture(self, temp):
        root = Path(temp)
        (root / "src").mkdir()
        (root / "configs/update-staging/v1.41.00").mkdir(parents=True)
        (root / "requirements.txt").write_text("ok-script==1.2.3\n", encoding="utf-8")
        (root / "requirements.in").write_text("ok-script==1.2.3\n", encoding="utf-8")
        (root / "src/example.py").write_text("old", encoding="utf-8")
        (root / "src/stale.py").write_text("stale", encoding="utf-8")
        (root / "configs/marker.json").write_text("preserve", encoding="utf-8")
        archive = root / "configs/update-staging/v1.41.00/update.zip"
        files = {"src/example.py": b"new", "requirements.txt": (root / "requirements.txt").read_bytes(),
                 "requirements.in": (root / "requirements.in").read_bytes()}
        manifest = {"version": "1.41.00", "framework": "ok-script==1.2.3",
                    "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
        with zipfile.ZipFile(archive, "w") as package:
            for name, data in files.items(): package.writestr(name, data)
            package.writestr("update-manifest.json", json.dumps(manifest))
        request = archive.parent / "apply-request.json"
        request.write_text(json.dumps({"schema_version": 1, "from_version": "1.40.02",
            "to_version": "1.41.00", "archive": str(archive.resolve()),
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "size": archive.stat().st_size,
            "install_root": str(root.resolve()), "parent_pid": 0,
            "restart_command": ["python", "main.py"]}), encoding="utf-8")
        return root, request

    @patch("src.update.lan_apply.subprocess.Popen")
    def test_applies_and_preserves_configs(self, popen):
        with tempfile.TemporaryDirectory() as temp:
            root, request = self.fixture(temp)
            result = apply_request(request)
            self.assertEqual("succeeded", result.status)
            self.assertEqual("new", (root / "src/example.py").read_text())
            self.assertFalse((root / "src/stale.py").exists())
            self.assertEqual("preserve", (root / "configs/marker.json").read_text())
            popen.assert_called_once()

    @patch('src.update.lan_apply.subprocess.Popen')
    def test_dependency_formatting_does_not_block_upgrade(self, popen):
        for content in (b'ok-script==1.2.3\n', b'ok-script==1.2.3\r\n',
                        b'\xef\xbb\xbf# generated\r\n\r\n  ok-script==1.2.3  \r\n'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as temp:
                root, request = self.fixture(temp)
                for name in ('requirements.txt', 'requirements.in'):
                    (root / name).write_bytes(content)
                result = apply_request(request)
                self.assertEqual('succeeded', result.status, result.message)
                self.assertEqual('preserve', (root / 'configs/marker.json').read_text())

    @patch('src.update.lan_apply.subprocess.Popen')
    def test_real_dependency_change_is_rejected_before_ready_or_replacement(self, popen):
        for name in ('requirements.txt', 'requirements.in'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root, request = self.fixture(temp)
                (root / name).write_bytes(b'ok-script==1.2.3\nnew-package==2.0\n')
                data = json.loads(request.read_text())
                data['parent_pid'] = os.getpid()
                request.write_text(json.dumps(data))
                result = apply_request(request)
                self.assertEqual('failed', result.status)
                self.assertIn(name, result.message)
                self.assertFalse(request.with_suffix('.ready.json').exists())
                self.assertEqual('old', (root / 'src/example.py').read_text())
                popen.assert_not_called()

    def test_legacy_repair_backs_up_formatting_and_preserves_configs(self):
        with tempfile.TemporaryDirectory() as temp:
            root, request = self.fixture(temp)
            data = json.loads(request.read_text())
            for name in ('requirements.txt', 'requirements.in'):
                (root / name).write_bytes(b'# local formatting\r\nok-script==1.2.3\r\n')
            backup = repair_legacy_requirements(root, Path(data['archive']), version=data['to_version'],
                                               sha256=data['sha256'], size=data['size'])
            for name in ('requirements.txt', 'requirements.in'):
                self.assertEqual(b'# local formatting\r\nok-script==1.2.3\r\n', (backup / name).read_bytes())
                with zipfile.ZipFile(data['archive']) as package:
                    self.assertEqual(package.read(name), (root / name).read_bytes())
            self.assertEqual('preserve', (root / 'configs/marker.json').read_text())

    def test_legacy_repair_rejects_real_change_without_partial_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            root, request = self.fixture(temp)
            data = json.loads(request.read_text())
            (root / 'requirements.txt').write_bytes(b'ok-script==1.2.3\r\n')
            (root / 'requirements.in').write_bytes(b'ok-script==1.2.3\nextra==1.0\n')
            with self.assertRaisesRegex(ValueError, '真实运行依赖'):
                repair_legacy_requirements(root, Path(data['archive']), version=data['to_version'],
                                           sha256=data['sha256'], size=data['size'])
            self.assertEqual(b'ok-script==1.2.3\r\n', (root / 'requirements.txt').read_bytes())
            self.assertFalse((root / 'configs/update-backups').exists())

    @patch("src.update.lan_apply.subprocess.Popen")
    def test_failure_rolls_back(self, popen):
        with tempfile.TemporaryDirectory() as temp:
            root, request = self.fixture(temp)
            calls = 0
            def fail_second(stage, path):
                nonlocal calls
                calls += 1
                if calls == 2: raise OSError("injected")
            result = apply_request(request, fault_hook=fail_second)
            self.assertEqual("rolled_back", result.status)
            self.assertEqual("old", (root / "src/example.py").read_text())
            self.assertEqual("stale", (root / "src/stale.py").read_text())


if __name__ == "__main__":
    unittest.main()
