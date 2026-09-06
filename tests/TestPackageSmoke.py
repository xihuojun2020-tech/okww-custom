import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.package_smoke import inspect_distribution, NOTIFICATION_TEMPLATE


class TestPackageSmoke(unittest.TestCase):
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
