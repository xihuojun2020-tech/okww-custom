import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.package_smoke import inspect_distribution, NOTIFICATION_TEMPLATE


class TestPackageSmoke(unittest.TestCase):
    def test_installer_source_layout_preserves_runtime_data_checks(self):
        from scripts.inspect_installer import inspect_extracted
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            reference = {'config.py': b'version = "1.33.01"\n', 'custom_ok/fix.py': b'pass\n'}
            for folder in ('repo', 'working'):
                source = root / 'data/apps/example' / folder
                for name, data in reference.items():
                    path = source / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data.replace(b'\n', b'\r\n'))
            metadata = root / 'data/apps/example/repo/.git/logs/HEAD'
            metadata.parent.mkdir(parents=True)
            metadata.write_text('synthetic public clone log', encoding='utf-8')
            result = inspect_extracted(root, reference, '1.33.01')
            self.assertEqual(len(result['source_trees']), 2)
            self.assertFalse(result['installation_tested'])
            self.assertFalse(result['startup_tested'])
            private = root / 'data/apps/example/working/configs/profile.json'
            private.parent.mkdir()
            private.write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '配置'):
                inspect_extracted(root, reference, '1.33.01')

    def test_installer_source_mismatch_is_not_accepted(self):
        from scripts.inspect_installer import inspect_extracted
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / 'data/apps/example/working/config.py'
            config.parent.mkdir(parents=True)
            config.write_text('version = "old"', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '不一致'):
                inspect_extracted(root, {'config.py': b'version = "new"'}, 'new')

    def inspect(self, name, value=b'{}'):
        with tempfile.TemporaryDirectory() as temp:
            dist = Path(temp)
            with zipfile.ZipFile(dist / 'candidate.zip', 'w') as package:
                package.writestr(name, value)
            return inspect_distribution(dist)

    def test_rejects_runtime_data_at_any_depth_case_or_separator(self):
        for prefix in ('', 'app/', 'app/version/deep/'):
            for name in ('configs/account_master_config.json', 'CONFIGS/Account.json',
                         'configs\\account.json', '运行状态/账号/a.json', 'logs/x.log',
                         'configs_backup/x.json', 'working/x', 'config_bundle_transactions/a'):
                with self.subTest(prefix=prefix, name=name), self.assertRaises(ValueError):
                    self.inspect(prefix + name)

    def test_rejects_absolute_traversal_and_runtime_directories(self):
        for name in ('../src/main.py', 'app/../../main.py', '/etc/file', 'C:\\configs\\x',
                     'app/logs/', 'app/configs/accounts/'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.inspect(name)

    def test_allows_code_assets_empty_config_and_sanitized_notification(self):
        for name in ('main.py', 'app/src/account_repository.py', 'app/assets/map.png', 'app/configs/'):
            self.assertEqual(len(self.inspect(name)), 1)
        for prefix in ('', 'app/', 'app/release/'):
            self.assertEqual(len(self.inspect(prefix + 'configs/Notification.json',
                                              json.dumps(NOTIFICATION_TEMPLATE).encode())), 1)

    def test_notification_exception_checks_content(self):
        for data in ({'Telegram Bot Token': 'synthetic-token'}, {'QQ Desktop Nickname': 'synthetic-name'},
                     {'Discord Notification': True}, {'unexpected': ''}, [], {'System Notification': 0}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.inspect('app/configs/notification.json', json.dumps(data).encode())

    def test_no_artifacts_or_only_non_package_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            dist = Path(temp)
            with self.assertRaises(ValueError):
                inspect_distribution(dist)
            (dist / 'README.md').write_text('text')
            with self.assertRaises(ValueError):
                inspect_distribution(dist)


if __name__ == '__main__':
    unittest.main()
