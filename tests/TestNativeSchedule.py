import json
import ctypes
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock
from xml.etree import ElementTree as ET

from src.native_schedule import NS, NativeSchedule, schedulable_tasks


class TestNativeSchedule(unittest.TestCase):
    def setUp(self):
        self.service = Mock()
        self.folder = Mock(Path='\\GameFrame')
        self.service.GetFolder.return_value.GetFolders.return_value = [self.folder]
        self.backend = NativeSchedule('package & 中文', 'data space', user='DOMAIN\\User', service=self.service)

    def value(self, **kwargs):
        return self.backend.preview('MultiAccountDailyTask', {'type': 'windows', 'title': 'A "B" & 中文'},
                                    start='2026-10-12T09:00:00', **kwargs)

    def test_stable_task_and_xml_escaping(self):
        tasks = [dict(id='MultiAccountDailyTask', name='daily', kind='one-shot', support_schedule_task=True),
                 dict(id='hidden', name='hidden', kind='one-shot', support_schedule_task=True, visible=False)]
        self.assertEqual(schedulable_tasks(tasks), schedulable_tasks(list(reversed(tasks))))
        value = self.value()
        self.assertEqual(value['argv'][value['argv'].index('--task') + 1], 'MultiAccountDailyTask')
        self.assertEqual(json.loads(value['argv'][-1])['title'], 'A "B" & 中文')
        root = ET.fromstring(value['xml'])
        self.assertEqual(root.findtext(f'{{{NS}}}Actions/{{{NS}}}Exec/{{{NS}}}Arguments'), value['arguments'])
        self.assertNotIn('main.py', value['arguments'])
        # Use Windows' real argv parser to cover quoted JSON and Unicode paths.
        count = ctypes.c_int()
        parser = ctypes.windll.shell32.CommandLineToArgvW
        parser.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
        parser.restype = ctypes.POINTER(ctypes.c_wchar_p)
        parsed = parser('python.exe ' + value['arguments'], ctypes.byref(count))
        try:
            self.assertEqual([parsed[index] for index in range(1, count.value)], value['argv'])
        finally:
            ctypes.windll.kernel32.LocalFree(ctypes.cast(parsed, ctypes.c_void_p))

    def test_all_trigger_contracts(self):
        for trigger, expected in [('once', 'TimeTrigger'), ('hours', 'TimeTrigger'),
                                   ('daily', 'CalendarTrigger'), ('days', 'CalendarTrigger'),
                                   ('weekly', 'CalendarTrigger'), ('monthly', 'CalendarTrigger')]:
            with self.subTest(trigger=trigger):
                root = ET.fromstring(self.value(trigger=trigger, interval=3)['xml'])
                self.assertIsNotNone(root.find(f'{{{NS}}}Triggers/{{{NS}}}{expected}'))

    def test_mock_register_list_delete_owned_only(self):
        value = self.value()
        name = self.backend.create(value)
        self.folder.RegisterTask.assert_called_once_with(name, value['xml'], 6, 'DOMAIN\\User', None, 3)
        own = Mock(Name=name, Xml=value['xml'], Enabled=True, NextRunTime='tomorrow', LastTaskResult=0)
        other = Mock(Name='unrelated')
        self.folder.GetTasks.return_value = [own, other]
        self.assertEqual(self.backend.list()[0]['binding'], value['binding'])
        self.backend.delete(name)
        self.service.GetFolder.return_value.DeleteTask.assert_called_once_with(name, 0)
        with self.assertRaises(ValueError):
            self.backend.delete('unrelated')

    def test_empty_device_rejected(self):
        with self.assertRaises(ValueError):
            self.backend.preview('daily', {}, start='2026-10-12T09:00:00')

    def test_installed_core_directory_and_user_ownership(self):
        import gameframe
        from unittest.mock import patch
        # A pack's src lives under payload; the interpreter must locate the actual core.
        with patch('src.native_schedule.__file__', str(Path('installed/payload/src/native_schedule.py'))):
            backend = NativeSchedule('package', 'data', user='DOMAIN\\One', service=self.service)
        self.assertEqual(backend.core_dir, str(Path(gameframe.__file__).resolve().parent.parent))
        other = NativeSchedule('package', 'data', user='DOMAIN\\Two', service=self.service)
        self.assertNotEqual(backend.prefix, other.prefix)
        with self.assertRaises(ValueError):
            other.delete(backend.prefix + 'schedule')

    def test_managed_schedule_stable_command_and_ownership_survive_active_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            installation = {'managed_root': str(root), 'bootstrap_pythonw': str(root / 'stable/pythonw.exe')}
            (root / 'installation.json').write_text(json.dumps(installation), encoding='utf-8')
            def backend(environment, data):
                package = root / 'versions' / environment / 'gamepacks/fixture_pack'
                package.mkdir(parents=True)
                (package / 'manifest.json').write_text('{"id":"fixture_pack"}', encoding='utf-8')
                (root / 'active.json').write_text(json.dumps({'environment': 'versions/' + environment,
                    'bundle': {'package_id': 'fixture_pack'}}), encoding='utf-8')
                return NativeSchedule(package, root / data, user='DOMAIN\\User',
                                      managed_root=root, service=self.service)
            first = backend('old', 'old-data')
            value = first.preview('daily', {'type': 'windows'}, start='2026-10-12T09:00:00')
            name = first.prefix + 'owned'
            second = backend('new', 'new-data')
            self.assertEqual(first.prefix, second.prefix)
            self.assertEqual(value['command'], installation['bootstrap_pythonw'])
            self.assertEqual(value['argv'][:5], [str(root / 'bootstrap.py'), '--managed-root', str(root),
                                               '--package-id', 'fixture_pack'])
            self.assertNotIn(str(root / 'versions'), value['arguments'])
            self.assertNotIn('--data-dir', value['argv'])
            xml = ET.fromstring(value['xml'])
            self.assertEqual(xml.findtext(f'{{{NS}}}Actions/{{{NS}}}Exec/{{{NS}}}WorkingDirectory'), str(root))
            own = Mock(Name=name, Xml=value['xml'], Enabled=True, NextRunTime='tomorrow', LastTaskResult=0)
            self.folder.GetTasks.return_value = [own]
            records = second.list()
            self.assertEqual(records[0]['name'], name)
            self.assertFalse(records[0]['requires_migration'])
            second.delete(name)
            self.service.GetFolder.return_value.DeleteTask.assert_called_once_with(name, 0)

    def test_managed_legacy_identification_and_explicit_delete_are_owned_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            package = root / 'versions/old/gamepacks/fixture_pack'
            package.mkdir(parents=True)
            (package / 'manifest.json').write_text('{"id":"fixture_pack"}', encoding='utf-8')
            (root / 'installation.json').write_text(json.dumps({'managed_root': str(root),
                'bootstrap_pythonw': str(root / 'stable/pythonw.exe')}), encoding='utf-8')
            (root / 'active.json').write_text(json.dumps({'environment': 'versions/old',
                'bundle': {'package_id': 'fixture_pack'}}), encoding='utf-8')
            old = NativeSchedule(package, root / 'data', user='DOMAIN\\User', service=self.service)
            other_user = NativeSchedule(package, root / 'data', user='DOMAIN\\Other', service=self.service)
            foreign = NativeSchedule(root / 'unmanaged', root / 'data', user='DOMAIN\\User', service=self.service)
            records = []
            for backend in (old, other_user, foreign):
                value = backend.preview('daily', {'type': 'windows'}, start='2026-10-12T09:00:00')
                records.append(Mock(Name=backend.prefix + 'owned', Xml=value['xml'], Enabled=True,
                                    NextRunTime='tomorrow', LastTaskResult=0))
            self.folder.GetTasks.return_value = records
            managed = NativeSchedule(package, root / 'data', user='DOMAIN\\User',
                                     managed_root=root, service=self.service)
            with self.assertRaises(ValueError): managed.delete(records[0].Name)
            identified = managed.list()
            self.assertEqual([record['name'] for record in identified], [records[0].Name])
            self.assertTrue(identified[0]['requires_migration'])
            self.assertIn('删除后重新创建', identified[0]['migration_notice'])
            self.folder.RegisterTask.assert_not_called()
            with self.assertRaises(ValueError): managed.create(managed.preview('daily', {'type': 'windows'},
                start='2026-10-12T09:00:00'), name=records[0].Name)
            managed.delete(records[0].Name)
            self.service.GetFolder.return_value.DeleteTask.assert_called_once_with(records[0].Name, 0)
            with self.assertRaises(ValueError): managed.delete(records[1].Name)
            with self.assertRaises(ValueError): managed.delete(records[2].Name)
