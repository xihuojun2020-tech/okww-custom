import json
import ctypes
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
