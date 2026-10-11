"""Real Qt device forms with synthetic windows and no capture/input startup."""

import unittest

class TestGameFrameDeviceEditor(unittest.TestCase):
    def run_probe(self, body):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        TestAccountManagementEntry().run_probe('''
            from unittest.mock import patch
            from PySide6.QtWidgets import QApplication
            from gameframe.device_editor import DeviceEditor
            from gameframe.devices.windows import WindowsDevice
            from gameframe.devices.mumu import MuMuDevice
            from gameframe.devices.adb import AdbDevice
            from gameframe.devices.replay import ReplayDevice
            app = QApplication([])
        ''' + body)

    def test_window_refresh_selection_manual_hwnd_and_launch_payload(self):
        self.run_probe('''
            calls = []
            def enumerate_fixture():
                calls.append('refresh')
                return [{'hwnd': 42, 'title': 'Synthetic target', 'pid': 7},
                        {'hwnd': 43, 'title': 'Synthetic dialog', 'pid': 7}]
            with patch.object(WindowsDevice, '__init__', side_effect=AssertionError('device started')):
                editor = DeviceEditor(window_enumerator=enumerate_fixture)
                editor.set_options({'type': 'windows', 'hwnd': 123,
                                    'capture_factory': {'advanced': [1, 2]}})
                assert calls == []
                changes = []
                editor.options_changed.connect(changes.append)
                editor.refresh_button.click()
                assert calls == ['refresh'] and editor.window_select.count() == 3
                assert changes == [] and editor.options()['hwnd'] == 123
                editor.window_select.setCurrentIndex(1)
                assert changes[-1]['hwnd'] == 42
                assert 'Synthetic target' in editor.window_select.itemText(1)
                assert 'PID 7' in editor.window_select.itemText(1)
                editor.fields['windows']['hwnd'].setText('0x2b')
                assert editor.window_select.currentData() == 43
                editor.refresh_button.click()
                assert calls == ['refresh', 'refresh']
                assert editor.window_select.currentData() == 43
                editor.fields['windows']['launch_command'].setPlainText('C:/synthetic/launcher.exe\\n--game\\nwith spaces')
                editor.fields['windows']['target_executable'].setText('C:/synthetic/game.exe')
                assert editor.options() == {
                    'type': 'windows', 'hwnd': 43, 'capture_factory': {'advanced': [1, 2]},
                    'launch_command': ['C:/synthetic/launcher.exe', '--game', 'with spaces'],
                    'target_executable': 'C:/synthetic/game.exe'}
                assert changes[-1] == editor.options()
                assert editor.capabilities() == WindowsDevice.capabilities
                assert 'keyboard' in editor.capabilities_label.text()
        ''')

    def test_all_backend_fields_and_advanced_options_round_trip(self):
        self.run_probe('''
            fixtures = [
                ({'type': 'mumu', 'install_dir': 'C:/synthetic/MuMu', 'instance_index': 3,
                  'dll_path': 'C:/synthetic/sdk.dll', 'package_name': 'game.example', 'app_index': 2,
                  'extra': {'unicode': '高级', 'nested': [True, None, 3]}}, MuMuDevice),
                ({'type': 'adb', 'serial': 'synthetic:5555', 'adb_path': 'C:/synthetic/adb.exe',
                  'extra': {'preserve': True}}, AdbDevice),
                ({'type': 'replay', 'frames': ['C:/synthetic/一.png', 'C:/synthetic/two.png'],
                  'extra': ['keep', 'all']}, ReplayDevice),
                ({'type': 'windows', 'hwnd': 40, 'launch_command': None,
                  'target_executable': None, 'extra': {'keep': True}}, WindowsDevice),
            ]
            editor = DeviceEditor(window_enumerator=lambda: [])
            for options, backend in fixtures:
                with patch.object(backend, '__init__', side_effect=AssertionError('device started')):
                    editor.set_options(options)
                    assert editor.options() == options
                    assert editor.capabilities() == backend.capabilities
                    returned = editor.options()
                    returned['extra'] = 'mutation'
                    assert editor.options() == options
            editor.set_options(fixtures[0][0])
            assert 'keyboard' not in editor.capabilities()
            assert 'keyboard' not in editor.capabilities_label.text()
            fields = editor.fields['mumu']
            fields['install_dir'].setText('D:/synthetic/MuMu')
            fields['instance_index'].setText('4')
            fields['dll_path'].setText('D:/synthetic/sdk.dll')
            fields['package_name'].setText('another.example')
            fields['app_index'].setText('1')
            assert editor.options() == {**fixtures[0][0], 'install_dir': 'D:/synthetic/MuMu',
                'instance_index': 4, 'dll_path': 'D:/synthetic/sdk.dll',
                'package_name': 'another.example', 'app_index': 1}
            editor.set_options(fixtures[1][0])
            editor.fields['adb']['serial'].setText('synthetic-two:5555')
            editor.fields['adb']['adb_path'].setText('D:/synthetic/adb.exe')
            assert editor.options() == {**fixtures[1][0], 'serial': 'synthetic-two:5555',
                'adb_path': 'D:/synthetic/adb.exe'}
            editor.set_options(fixtures[2][0])
            editor.fields['replay']['frames'].setPlainText('D:/synthetic/a.png\\nD:/synthetic/b.png')
            assert editor.options() == {**fixtures[2][0], 'frames': ['D:/synthetic/a.png', 'D:/synthetic/b.png']}
        ''')

    def test_backend_selection_keeps_each_backend_parameters_and_reports_invalid_integer(self):
        self.run_probe('''
            editor = DeviceEditor(window_enumerator=lambda: [])
            editor.set_options({'type': 'mumu', 'install_dir': 'synthetic', 'instance_index': 3,
                                'package_name': None, 'extra': ['retain']})
            changes = []
            editor.options_changed.connect(changes.append)
            original = editor.options()
            try:
                editor.set_options({})
            except ValueError as error:
                assert 'JSON object with a type' in str(error)
            else:
                raise AssertionError('missing device type accepted')
            assert editor.options() == original and changes == []
            editor.fields['mumu']['instance_index'].setText('not a number')
            assert changes == [] and 'must be an integer' in editor.error_label.text()
            try:
                editor.options()
            except ValueError:
                pass
            else:
                raise AssertionError('invalid instance index silently accepted')
            editor.backend_select.setCurrentIndex(editor.backend_select.findData('adb'))
            assert editor.backend_select.currentData() == 'mumu'
            editor.fields['mumu']['instance_index'].setText('5')
            assert changes[-1]['instance_index'] == 5 and editor.error_label.text() == ''
            editor.backend_select.setCurrentIndex(editor.backend_select.findData('adb'))
            assert editor.options() == {'type': 'adb', 'serial': ''}
            editor.backend_select.setCurrentIndex(editor.backend_select.findData('mumu'))
            assert editor.options() == {'type': 'mumu', 'install_dir': 'synthetic',
                'instance_index': 5, 'package_name': None, 'extra': ['retain']}
            editor.fields['mumu']['package_name'].setText('game.synthetic')
            editor.fields['mumu']['package_name'].setText('')
            assert 'package_name' not in editor.options()
            editor.setEnabled(False)
            assert not editor.refresh_button.isEnabled()
            assert not editor.backend_select.isEnabled()
            assert not editor.fields['mumu']['instance_index'].isEnabled()
        ''')

    def test_refresh_failure_is_visible_and_read_only_enumerator_filters_windows(self):
        self.run_probe('''
            from contextlib import ExitStack
            from types import SimpleNamespace
            from gameframe.devices.windows import enumerate_windows
            with ExitStack() as stack:
                stack.enter_context(patch('gameframe.devices.windows.enumerate_windows',
                    side_effect=AssertionError('automatic window enumeration')))
                for backend in (WindowsDevice, MuMuDevice, AdbDevice, ReplayDevice):
                    stack.enter_context(patch.object(backend, '__init__',
                        side_effect=AssertionError('editor started device')))
                untouched = DeviceEditor()
                for options in ({'type': 'windows', 'hwnd': 42},
                                {'type': 'mumu', 'install_dir': 'synthetic', 'instance_index': 0},
                                {'type': 'adb', 'serial': 'synthetic'},
                                {'type': 'replay', 'frames': []}):
                    untouched.set_options(options)
                    assert untouched.options() == options
            def fail():
                raise OSError('synthetic enumeration failure')
            editor = DeviceEditor(window_enumerator=fail)
            editor.set_options({'type': 'windows', 'hwnd': 42})
            editor.refresh_button.click()
            assert 'synthetic enumeration failure' in editor.error_label.text()
            assert editor.options() == {'type': 'windows', 'hwnd': 42}
            gui = SimpleNamespace(
                GetWindowText=lambda hwnd: {1: 'Visible', 2: 'Hidden', 3: ''}[hwnd],
                IsWindowVisible=lambda hwnd: hwnd != 2,
                EnumWindows=lambda callback, context: [callback(hwnd, context) for hwnd in (1, 2, 3)])
            process = SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (4, 7))
            with patch.dict('sys.modules', {'win32gui': gui, 'win32process': process}):
                assert enumerate_windows() == [{'hwnd': 1, 'title': 'Visible', 'pid': 7}]
        ''')

    def test_six_language_schema_labels_redraw_forms_errors_without_changing_device_values(self):
        self.run_probe('''
            import gettext, json
            from contextlib import ExitStack
            from gameframe.gui import GameFrameWindow
            from gameframe.ui_strings import LABELS
            packages = root / 'packages'
            package = packages / 'localized-fixture'
            package.mkdir(parents=True)
            (package / 'plugin.py').write_text('raise AssertionError("package imported")')
            (package / 'manifest.json').write_text(json.dumps({
                'api_version': 1, 'id': 'localized-fixture', 'version': '1.00.00',
                'entrypoint': 'plugin.py:Package', 'license': 'test', 'platforms': ['windows'],
                'execution': 'native', 'tasks': []}))
            context = dict(sequences=[], sequence=None, accounts=[], account=None,
                           verified_account=None, summary='', reason='')
            with ExitStack() as stack:
                stack.enter_context(patch('gameframe.devices.windows.enumerate_windows',
                    side_effect=AssertionError('real window enumeration')))
                for backend in (WindowsDevice, MuMuDevice, AdbDevice, ReplayDevice):
                    stack.enter_context(patch.object(backend, '__init__',
                        side_effect=AssertionError('device started')))
                window = GameFrameWindow(packages, root / 'data', key_state=lambda key: False)
                editor = window.device_editor
                changes = []
                editor.options_changed.connect(changes.append)
                assert editor.refresh_button.text() == 'Refresh windows'
                assert editor.window_select.itemText(0) == 'Refresh to list visible windows'
                for locale in ('en_US', 'zh_CN', 'zh_TW', 'ja_JP', 'ko_KR', 'es_ES'):
                    with (Path(sys.argv[1]) / 'i18n' / locale / 'LC_MESSAGES/native.mo').open('rb') as stream:
                        translate = gettext.GNUTranslations(stream).gettext
                    labels = {source: translate(source) for source in LABELS}
                    options = {'type': 'windows', 'hwnd': 42,
                               'launch_command': ['C:/User path/launcher.exe', '--game'],
                               'target_executable': 'C:/User path/game.exe',
                               'capture_method': 'WGC', 'input_method': 'PostMessage'}
                    editor.set_options(options)
                    changes.clear()
                    window._apply_account_context({'ok': True, 'schema': {'launcher_labels': labels},
                                                   'result': context})
                    assert editor.options() == options and changes == []
                    for source, label in editor._label_widgets:
                        assert label.text() == translate(source), (locale, source)
                    assert editor.backend_select.itemText(0) == translate('Windows HWND')
                    assert editor.backend_select.itemData(0) == 'windows'
                    assert editor.refresh_button.text() == translate('Refresh windows')
                    assert editor.fields['windows']['capture_method'].currentText() == 'WGC'
                    assert editor.fields['windows']['input_method'].currentText() == 'PostMessage'
                    assert editor.capabilities_label.text() == translate('Capabilities: {capabilities}').format(
                        capabilities=', '.join(sorted(editor.capabilities())))
                    editor._window_enumerator = lambda: [{'title': 'User 窗口 title', 'pid': 7, 'hwnd': 42}]
                    editor.refresh_button.click()
                    assert editor.window_select.itemText(0) == translate('Select a window or enter HWND below')
                    assert editor.window_select.itemText(1) == 'User 窗口 title — PID 7 — HWND 0x2a'
                    assert editor.options() == options and changes == []
                    editor.fields['windows']['hwnd'].setText('-1')
                    expected = translate('{field} cannot be negative').format(field=translate('HWND (decimal or 0x)'))
                    assert editor.error_label.text() == expected
                    editor.fields['windows']['hwnd'].setText('invalid')
                    expected = translate('{field} must be an integer').format(field=translate('HWND (decimal or 0x)'))
                    assert editor.error_label.text() == expected
                    editor.apply_labels({})
                    assert editor.error_label.text() == 'HWND (decimal or 0x) must be an integer'
                    editor.apply_labels(labels)
                    assert editor.error_label.text() == expected
                    editor.set_options(options)
                    def fail(): raise OSError('User path {raw}')
                    editor._window_enumerator = fail
                    editor.refresh_button.click()
                    assert editor.error_label.text() == translate('Window enumeration failed: {error}').format(error='User path {raw}')
                    editor.apply_labels({})
                    assert editor.error_label.text() == 'Window enumeration failed: User path {raw}'
                    try: editor.set_options({'type': 'unknown'})
                    except ValueError as error: assert str(error) == 'Unknown device type: unknown'
                    else: raise AssertionError('unknown type accepted')
                window._select_package(0)
                assert editor.refresh_button.text() == 'Refresh windows'
                window.timer.stop()
                window._closing = True
                window._cleanup_done = True
                window.close()
        ''')


if __name__ == '__main__':
    unittest.main()
