"""Synthetic language owners, real offscreen Qt widgets and headless hosts."""
import ast
import gettext
import json
from pathlib import Path
import shutil
from string import Formatter
import tempfile
import unittest
import zipfile

from src.runtime.native_language import (LANGUAGE_OPTIONS, create_language_config,
    language_preference, load_language, resolve_language)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'gamepacks/wuthering_waves_native'


class TestNativeLanguage(unittest.TestCase):
    def test_all_choices_and_auto_system_locales(self):
        with tempfile.TemporaryDirectory() as directory:
            config = create_language_config(directory)
            for selected in LANGUAGE_OPTIONS[:-1]:
                with self.subTest(selected=selected):
                    config['Language'] = selected
                    language = load_language(directory, pack_root=PACK)
                    self.assertEqual((language.selected, language.resolved), (selected, selected))
                    self.assertTrue(language.translate('建立首个账号'))
            config['Language'] = 'en_US'
            english = load_language(directory)
            self.assertEqual(english.translate('Auto Combat'), 'Auto Combat')
            self.assertEqual(english.translate('建立首个账号'), 'Create first account')
            config['Language'] = 'zh_CN'
            self.assertEqual(load_language(directory).translate('Auto Combat'), '自动战斗')
            config['Language'] = 'Auto'
            for system, resolved in {'zh-CN': 'zh_CN', 'zh-SG': 'zh_CN',
                'zh-Hant': 'zh_TW', 'zh-HK': 'zh_TW', 'zh-TW': 'zh_TW',
                'en-GB': 'en_US', 'es-MX': 'es_ES', 'ja-JP': 'ja_JP',
                'ko-KR': 'ko_KR', 'de-DE': 'en_US'}.items():
                with self.subTest(system=system):
                    self.assertEqual(load_language(directory, system_locale=system).resolved, resolved)

    def test_legacy_migration_native_precedence_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'configs'
            folder.mkdir()
            old = folder / 'ui_config.json'
            old.write_text(json.dumps({'MainWindow': {'Language': 'ja_JP'}}), encoding='utf-8')
            original = old.read_bytes()
            self.assertEqual(language_preference(root), 'ja_JP')
            self.assertFalse((folder / 'Language.json').exists())
            config = create_language_config(root)
            self.assertEqual(config['Language'], 'ja_JP')
            self.assertEqual(json.loads(config.config_file.read_text(encoding='utf-8')), {'Language': 'ja_JP'})
            loaded = load_language(root)
            config['Language'] = 'en_US'
            self.assertEqual(loaded.resolved, 'ja_JP')
            self.assertEqual(load_language(root).resolved, 'en_US')
            self.assertEqual(create_language_config(root)['Language'], 'en_US')
            self.assertEqual(old.read_bytes(), original)

    def test_invalid_external_preference_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / 'configs'
            folder.mkdir()
            for value in ('fr_FR', None, True):
                with self.subTest(value=value):
                    (folder / 'Language.json').write_text(json.dumps({'Language': value}), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        load_language(directory)
            with self.assertRaises(ValueError):
                resolve_language('fr_FR')

    def test_installed_pack_path_and_required_resource_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / 'installed'
            package.mkdir()
            (package / 'manifest.json').write_text('{"source_root":"payload"}', encoding='utf-8')
            shutil.copytree(ROOT / 'i18n', package / 'payload/i18n')
            create_language_config(root / 'data')['Language'] = 'en_US'
            # The temporary installation is outside cwd and has a distinct payload.
            language = load_language(root / 'data', pack_root=package)
            self.assertEqual(language.catalogs, package / 'payload/i18n')
            self.assertEqual(language.translate('建立首个账号'), 'Create first account')
            (package / 'payload/i18n/en_US/LC_MESSAGES/native.mo').unlink()
            with self.assertRaises(FileNotFoundError):
                load_language(root / 'data', pack_root=package)

    def test_native_catalog_syntax_coverage_and_binary_matches_source(self):
        import polib
        from gameframe.ui_strings import LABELS
        from src.runtime.native_metadata import GLOBAL_METADATA
        from src.runtime.native_program_preferences import DEFAULTS
        msgids = set()
        for name in ('ManagementWindow', 'NativeExecutionOverviewDialog', 'NativeStorageTab',
                     'NativeConfigurationTab', 'NativeUserTaskTab', 'NativeCharacterCodeTab'):
            tree = ast.parse((ROOT / f'src/gui/{name}.py').read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == 'translate' and node.args
                    and isinstance(node.args[0], ast.Constant)):
                    msgids.add(node.args[0].value)
        msgids.update(('数据根（配置权威）', '日志', '截图', '诊断', '配置备份', '完成证据',
                       '运行控制状态（不迁移）'))
        msgids.update(LABELS)
        msgids.update(DEFAULTS)
        preferences = GLOBAL_METADATA['Program Preferences']
        msgids.update(('Program Preferences', preferences['description'], 'Auto'))
        msgids.update(preferences['config_description'].values())
        manifest = json.loads((PACK / 'manifest.json').read_text(encoding='utf-8'))
        msgids.update(task['category'] for task in manifest['tasks'])
        for locale in LANGUAGE_OPTIONS[:-1]:
            path = ROOT / f'i18n/{locale}/LC_MESSAGES/native.po'
            catalog = polib.pofile(str(path), check_for_duplicates=True)
            self.assertFalse(msgids - {entry.msgid for entry in catalog}, locale)
            with path.with_suffix('.mo').open('rb') as stream:
                compiled = gettext.GNUTranslations(stream)
            for entry in catalog:
                self.assertTrue(entry.msgstr, (locale, entry.msgid))
                self.assertEqual(compiled.gettext(entry.msgid), entry.msgstr)
                fields = lambda text: {name for _, name, _, _ in Formatter().parse(text) if name is not None}
                self.assertEqual(fields(entry.msgid), fields(entry.msgstr), (locale, entry.msgid))

    def test_offscreen_management_subtabs_and_overview_text(self):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        TestAccountManagementEntry().run_probe('''
            from types import SimpleNamespace
            from unittest.mock import patch
            from PySide6.QtWidgets import QApplication, QLabel, QDialogButtonBox
            from src.runtime.native_language import create_language_config, load_language, install_qt_language
            from src.management import AccountManagementService
            from src.gui.ManagementWindow import ManagementWindow
            from src.gui.NativeConfigurationTab import NativeConfigurationTab
            from src.gui.NativeUserTaskTab import NativeUserTaskTab, TEMPLATE
            from src.gui.NativeCharacterCodeTab import NativeCharacterCodeTab
            from src.gui.NativeStorageTab import NativeStorageTab
            from src.runtime.native_storage import NativeStorageService
            from src.gui.NativeExecutionOverviewDialog import NativeExecutionOverviewDialog
            data=root/'data'
            config=create_language_config(data)
            config['Language']='en_US'
            app=QApplication([])
            install_qt_language(app,load_language(data))
            assert len(app._native_language_translators)==2
            service=AccountManagementService(data,'language-test')
            with patch.object(ManagementWindow,'refresh'):
                window=ManagementWindow(service)
            assert window.windowTitle()=='Wuthering Waves accounts and completion evidence'
            assert window.first_button.text()=='Create first account'
            manifest=Path(sys.argv[1])/'gamepacks/wuthering_waves_native/manifest.json'
            with patch.object(NativeConfigurationTab,'_start'):
                configuration=NativeConfigurationTab(data,'language-test',manifest)
                user=NativeUserTaskTab(configuration)
                character=NativeCharacterCodeTab(configuration)
                storage=NativeStorageTab(NativeStorageService(data),lambda *args:None)
                repository=SimpleNamespace(list_profiles=lambda:[])
                reader=SimpleNamespace(directory=data,owners=lambda:[])
                overview=NativeExecutionOverviewDialog(repository,reader)
                app.processEvents()
                assert configuration.refresh_button.text()=='Refresh configuration'
                assert user.new_button.text()=='Create task'
                assert user.code.toPlainText()==TEMPLATE
                assert character.refresh_button.text()=='Refresh characters'
                assert [character.mode.itemText(i) for i in range(2)]==['Built-in code','Custom code']
                user._listed({'tasks':[],'catalog_revision':'abcdef1234567890'})
                assert 'Loaded 0 user tasks; saved revision abcdef123456' in user.status.text()
                character._listed({'characters':[],'saved_revision':'abcdef1234567890'})
                assert 'Loaded 0 characters; saved revision abcdef123456' in character.status.text()
                assert storage.select_button.text()=='Select output folder'
                assert 'Data root (configuration authority)' in [label.text() for label in storage.findChildren(QLabel)]
                storage._previewed({'files':2,'bytes':1048576})
                assert storage.status.text().startswith('Output migration preview: 2 files, 1.00 MiB.')
                assert overview.windowTitle()=='Execution status and daily timings (read only)'
                assert overview.workers.itemText(0)=='No execution process'
                close=overview.findChild(QDialogButtonBox).button(QDialogButtonBox.Close).text()
                assert close.replace('&','')=='Close',repr(close)
                config['Language']='zh_CN'
                assert window.first_button.text()=='Create first account'
                # A fresh process startup installs the newly loaded language.
                for translator in app._native_language_translators:app.removeTranslator(translator)
                install_qt_language(app,load_language(data))
                assert QLabel().tr('Auto Combat')=='自动战斗'
                assert QLabel().tr('Close')=='关闭'
                with patch.object(configuration,'_set') as save:
                    choice=configuration._widget('global','Program Preferences','Use DirectML',
                        'Auto','Auto',{'type':'drop_down','options':['Auto','Yes','No']},{})
                    assert choice.itemText(0)=='自动' and choice.itemData(0)=='Auto'
                    choice.setCurrentIndex(1)
                    save.assert_called_once_with('global','Program Preferences','Use DirectML','Yes')
                chinese_buttons=QDialogButtonBox(QDialogButtonBox.Close)
                chinese_close=chinese_buttons.button(QDialogButtonBox.Close).text()
                assert chinese_close.replace('&','')=='关闭',repr(chinese_close)
                overview.timer.stop()
                configuration.shutdown()
                for widget in (overview,storage,character,user,configuration,window):widget.deleteLater()
                app.processEvents()
        ''')

    def test_headless_configuration_host_translates_without_qt(self):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        TestAccountManagementEntry().run_probe('''
            from tests.TestNativeWWOneTime import BlockApplicationImports
            sys.meta_path.insert(0,BlockApplicationImports())
            from tests.fixture_support import make_account_environment
            data=root/'data'
            make_account_environment(data)
            from src.runtime.native_language import create_language_config
            create_language_config(data)['Language']='zh_CN'
            from src.runtime.native_configuration import create_configuration_host
            manifest=Path(sys.argv[1])/'gamepacks/wuthering_waves_native/manifest.json'
            host=create_configuration_host(data,'language-test',manifest,lambda event:None)
            assert host._app.tr('Auto Combat')=='自动战斗'
            assert host._app.tr('建立首个账号')=='建立首个账号'
            assert not any(name.split('.')[0] in ('ok','PySide6','qfluentwidgets','onnxocr') for name in sys.modules)
        ''')

    def test_configuration_child_metadata_and_restart_contract(self):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        package_labels = {'zh_CN': '游戏包', 'zh_TW': '遊戲包', 'en_US': 'Package',
                          'es_ES': 'Paquete', 'ja_JP': 'ゲームパッケージ', 'ko_KR': '게임 패키지'}
        for selected in LANGUAGE_OPTIONS[:-1]:
            with self.subTest(selected=selected):
                body = '''
                    from tests.TestNativeWWOneTime import BlockApplicationImports
                    sys.meta_path.insert(0,BlockApplicationImports())
                    from tests.fixture_support import make_account_environment
                    data=root/'data'
                    make_account_environment(data)
                    from src.runtime.native_language import create_language_config
                    create_language_config(data)['Language']=SELECTED
                    from src.runtime.native_configuration import main
                    manifest=Path(sys.argv[1])/'gamepacks/wuthering_waves_native/manifest.json'
                    assert main(['--data-dir',str(data),'--version','language-test',
                                 '--manifest',str(manifest)])==0
                    assert not any(name.split('.')[0] in ('ok','PySide6','qfluentwidgets','onnxocr') for name in sys.modules)
                '''.replace('SELECTED', repr(selected))
                requests = [dict(command='get-schema', request_id='initial'),
                            dict(command='set-config', request_id='save', scope='global',
                                 id='Language', values={'Language': 'en_US'})]
                output = TestAccountManagementEntry().run_probe(
                    body, stdin=''.join(json.dumps(request) + '\n' for request in requests))
                replies = [json.loads(line) for line in output.splitlines()]
                replies = [reply for reply in replies if reply['event'] == 'configuration-response']
                self.assertEqual(len(replies), 2)
                for response in replies:
                    self.assertTrue(response['ok'], response)
                    schema = response['schema']
                    self.assertEqual(schema['launcher_labels']['Package'], package_labels[selected])
                    globals_ = {entry['id']: entry for entry in schema['globals']}
                    language = globals_['Language']
                    self.assertEqual(language['config_type']['Language']['options'], list(LANGUAGE_OPTIONS))
                    self.assertTrue(language['config_type']['Language']['restart_required'])
                    self.assertEqual(set(language['current_config']), {'Language'})
                    self.assertEqual(set(globals_['Program Preferences']['current_config']),
                                     {'Auto Resize Game Window', 'Mute Game while in Background',
                                      'Exit App when Game Exits', 'Trigger Interval', 'Use DirectML'})
                saved = next(entry for entry in replies[1]['schema']['globals'] if entry['id'] == 'Language')
                self.assertEqual(saved['current_config']['Language'], 'en_US')
                tasks = {entry['id']: entry for entry in replies[0]['schema']['tasks']}
                if selected == 'zh_CN':
                    self.assertEqual(tasks['auto-combat']['name'], '⚔️ 自动战斗')
                    self.assertIn('Auto Target', tasks['auto-combat']['default_config'])
                    self.assertEqual(globals_['Program Preferences']['description'], '窗口、音频与推理偏好')
                elif selected == 'en_US':
                    self.assertEqual(tasks['auto-combat']['name'], '⚔️ Auto Combat')

    def test_native_zip_contains_all_catalogs_and_notice(self):
        from scripts.build_native_gamepack import build_native_gamepack
        with tempfile.TemporaryDirectory() as directory:
            output = build_native_gamepack(Path(directory) / 'fixture.zip')
            with zipfile.ZipFile(output) as archive:
                prefix = 'wuthering_waves_native/payload/'
                self.assertIn(prefix + 'i18n/README.native.md', archive.namelist())
                for locale in LANGUAGE_OPTIONS[:-1]:
                    for suffix in ('po', 'mo'):
                        name = f'i18n/{locale}/LC_MESSAGES/native.{suffix}'
                        self.assertEqual(archive.read(prefix + name), (ROOT / name).read_bytes())
                for path in (ROOT / 'i18n').glob('*/LC_MESSAGES/ok.mo'):
                    self.assertEqual(archive.read(prefix + path.relative_to(ROOT).as_posix()), path.read_bytes())


if __name__ == '__main__':
    unittest.main()
