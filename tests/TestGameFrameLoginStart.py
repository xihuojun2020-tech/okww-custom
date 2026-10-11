# SPDX-License-Identifier: MIT
"""No actual registry access; exercise command and native adapter contracts."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

from gameframe import login_start as login
from gameframe import login_start_controls as controls
from gameframe import managed_login_start as managed

ROOT = r'C:\Program Files\GameFrame'
ARGV = [ROOT + r'\runtime\pythonw.exe', '-m', 'gameframe', 'gui', '--packages',
        ROOT + r'\gamepacks', '--data-dir', r'C:\Users\Fixture\GameFrame Data']


class FakeWinreg:
    HKEY_CURRENT_USER, KEY_SET_VALUE, REG_SZ = 'HKCU', 2, 1
    def __init__(self):
        self.values = {'OtherApp': ('unrelated-command', self.REG_SZ)}
        self.calls = []
        self.fail = False
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def OpenKey(self, hive, key, *access):
        self.calls.append((hive, key, access))
        return self
    CreateKeyEx = OpenKey
    def QueryValueEx(self, key, name):
        if name not in self.values: raise FileNotFoundError(name)
        return self.values[name]
    def SetValueEx(self, key, name, reserved, kind, value):
        if self.fail: raise PermissionError('fixture save denied')
        self.values[name] = (value, kind)
    def DeleteValue(self, key, name):
        if self.fail: raise PermissionError('fixture remove denied')
        if name not in self.values: raise FileNotFoundError(name)
        del self.values[name]


class TestLoginStart(unittest.TestCase):
    def adapter(self):
        registry = FakeWinreg()
        with patch.dict(sys.modules, winreg=registry):
            adapter = login.CurrentUserRun()
        return registry, adapter

    def test_current_user_own_value_full_quoted_gui_command_and_disable(self):
        registry, adapter = self.adapter()
        command = login.configure_login_start(True, ARGV, installation_root=ROOT, registry=adapter)
        self.assertEqual(command, '"C:\\Program Files\\GameFrame\\runtime\\pythonw.exe" -m gameframe gui '
            '--packages "C:\\Program Files\\GameFrame\\gamepacks" --data-dir "C:\\Users\\Fixture\\GameFrame Data" '
            '--installed-root "C:\\Program Files\\GameFrame" --login-pythonw "C:\\Program Files\\GameFrame\\runtime\\pythonw.exe"')
        self.assertEqual(login.read_login_start(adapter), command)
        login.configure_login_start(False, None, installation_root=None, registry=adapter)
        self.assertIsNone(login.read_login_start(adapter))
        login.configure_login_start(False, None, installation_root=None, registry=adapter)
        self.assertEqual(registry.values, {'OtherApp': ('unrelated-command', registry.REG_SZ)})
        self.assertTrue(all(call[:2] == ('HKCU', login.RUN_KEY) for call in registry.calls))

    def test_failed_save_preserves_registry_and_saved_combat_intent(self):
        registry, adapter = self.adapter()
        context = {'restore_services': True, 'login_start': False}
        combat = {'_enabled': False}
        registry.fail = True
        for enabled in (True, False):
            with self.assertRaises(PermissionError):
                command = login.configure_login_start(enabled, ARGV, installation_root=ROOT, registry=adapter)
                context['login_start'] = command is not None
        self.assertEqual(context, {'restore_services': True, 'login_start': False})
        self.assertEqual(combat, {'_enabled': False})
        self.assertNotIn(login.VALUE_NAME, registry.values)

    def test_refuses_source_temporary_relative_and_non_gui_entries_before_adapter(self):
        entries = [
            [*ARGV[:3], 'run', *ARGV[4:]],
            ARGV + ['--task', 'auto-combat'],
            [r'C:\repo\.venv\Scripts\pythonw.exe', *ARGV[1:]],
            [r'C:\Users\Fixture\Temp\pythonw.exe', *ARGV[1:]],
            ['runtime\\pythonw.exe', *ARGV[1:]],
            [r'C:\checkout\test_out\runtime\pythonw.exe', *ARGV[1:]],
        ]
        with patch.object(login, 'CurrentUserRun') as native:
            for argv in entries:
                with self.subTest(argv=argv), self.assertRaises(ValueError):
                    login.configure_login_start(True, argv, installation_root=ROOT)
            native.assert_not_called()

    def test_import_and_command_build_do_not_create_registry_adapter(self):
        with patch.object(login, 'CurrentUserRun') as native:
            login.login_command(ARGV, ROOT)
            native.assert_not_called()

    def test_gui_construct_does_not_register_save_consumes_and_failure_does_not_persist(self):
        class Widget:
            def __init__(self, text):
                self.checked = False
                self.clicked = SimpleNamespace(connect=lambda callback: setattr(self, 'save', callback))
            def setChecked(self, value): self.checked = value
            def isChecked(self): return self.checked
        persisted, statuses = [], []
        window = SimpleNamespace(_launcher_context={'login_start': False, 'restore_services': True}, _launcher_labels={},
            status_label=SimpleNamespace(setText=statuses.append))
        window._save_launcher_context = lambda: persisted.append(dict(window._launcher_context))
        form = SimpleNamespace(addRow=lambda *args: None)
        registry, adapter = self.adapter()
        with patch.object(login, 'CurrentUserRun', return_value=adapter) as native, \
             patch.object(controls, 'QCheckBox', Widget), patch.object(controls, 'QPushButton', Widget):
            controls.attach_login_start(window, form, launch_argv=ARGV, installation_root=ROOT)
            native.assert_not_called()
            window.login_start.setChecked(True)
            window.login_start_save.save()
            self.assertEqual(persisted, [{'login_start': True, 'restore_services': True}])
            old_command = registry.values[login.VALUE_NAME]
            registry.fail = True
            window.login_start.setChecked(False)
            window.login_start_save.save()
            self.assertTrue(window.login_start.isChecked())
            self.assertEqual(len(persisted), 1)
            self.assertEqual(registry.values[login.VALUE_NAME], old_command)
            self.assertIn('未保存', statuses[-1])

    def test_managed_login_uses_stable_bootstrap_and_rejects_versioned_entry(self):
        installation = {'managed_root': ROOT,
                        'bootstrap_pythonw': ROOT + r'\bootstrap-runtime\pythonw.exe'}
        self.assertEqual(managed.managed_login_command(installation),
            '"C:\\Program Files\\GameFrame\\bootstrap-runtime\\pythonw.exe" '
            '"C:\\Program Files\\GameFrame\\bootstrap.py" --managed-root "C:\\Program Files\\GameFrame"')
        installation['bootstrap_pythonw'] = ROOT + r'\versions\old\Scripts\pythonw.exe'
        with self.assertRaisesRegex(ValueError, 'versioned'):
            managed.managed_login_command(installation)
        registry, adapter = self.adapter()
        adapter.write('old-entry')
        managed.configure_managed_login_start(False, None, registry=adapter)
        self.assertIsNone(adapter.read())


if __name__ == '__main__':
    unittest.main()
