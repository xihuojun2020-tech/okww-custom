"""Real configuration objects without models, device, legacy application or Qt."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.TestNativeWWOneTime import BlockApplicationImports

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'gamepacks/wuthering_waves_native/manifest.json'


class TestNativeConfiguration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.blocker = BlockApplicationImports()
        sys.meta_path.insert(0, cls.blocker)
        from tests.fixture_support import make_account_environment
        make_account_environment(cls.root)
        from src.runtime.native_configuration import create_configuration_host
        cls.events = []
        cls.host = create_configuration_host(cls.root, 'test', MANIFEST, cls.events.append)

    @classmethod
    def tearDownClass(cls):
        from src.evidence.service import get_evidence_service
        get_evidence_service().close()
        sys.meta_path.remove(cls.blocker)
        cls.temp.cleanup()

    def request(self, command, **values):
        return self.host.configuration_request({'request_id': 'test', 'command': command, **values})

    def test_all_real_metadata_without_device_or_models(self):
        response = self.request('get-schema')
        self.assertTrue(response['ok'], response)
        schema = json.loads(json.dumps(response['schema']))
        self.assertEqual(len(schema['tasks']), 29)
        self.assertEqual({entry['id'] for entry in schema['globals']},
                         {'Game Hotkey', 'Character Config', 'Monthly Card Config', 'Language', 'Program Preferences', 'Native Notifications'})
        self.assertTrue(all(entry['readonly_values'] == {} for entry in schema['globals']))
        tasks = {task['id']: task for task in schema['tasks']}
        self.assertFalse(tasks['MaterialPlannerTask']['visible'])
        for task in tasks.values():
            for definition in task['config_type'].values():
                for button in definition.get('buttons', []):
                    self.assertTrue(button['action_id'])
                    self.assertIn(button['target'], ('owner', 'management'))
        subconfigs = [definition['sub_configs'] for definition in tasks['DailyTask']['config_type'].values()
                      if 'sub_configs' in definition]
        self.assertTrue(any(type(item['value']) is bool for group in subconfigs for item in group))
        self.assertIsNone(self.host.context.device)
        self.assertIsNone(self.host.executor._frame)
        self.assertFalse(any(name.split('.')[0] in {'ok', 'og', 'PySide6', 'PyQt5', 'PyQt6', 'onnxocr'}
                             for name in sys.modules))

    def test_global_save_and_invalid_external_values(self):
        response = self.request('set-config', scope='global', id='Monthly Card Config',
                                values={'Monthly Card Time': 9})
        self.assertTrue(response['ok'], response)
        path = self.host.global_configs['Monthly Card Config'].config_file
        before = path.read_bytes()
        for values in ({'Monthly Card Time': 24}, {'Monthly Card Time': True}, {'unknown': 1}):
            response = self.request('set-config', scope='global', id='Monthly Card Config', values=values)
            self.assertFalse(response['ok'])
            self.assertEqual(path.read_bytes(), before)
        self.assertEqual(json.loads(before)['Monthly Card Time'], 9)

    def test_task_validator_rejects_without_writing_and_saved_value_reloads(self):
        task = next(task for task in self.host.tasks.values() if type(task).__name__ == 'PianoTeachingTask')
        response = self.request('set-config', scope='task', id='PianoTeachingTask',
                                values={'Sample Interval': 0.06})
        self.assertTrue(response['ok'], response)
        before = task.config.config_file.read_bytes()
        for values in ({'Sample Interval': 0.5}, {'Sample Interval': True}, {'unknown': 1}):
            response = self.request('set-config', scope='task', id='PianoTeachingTask', values=values)
            self.assertFalse(response['ok'], response)
            self.assertEqual(task.config.config_file.read_bytes(), before)
        from src.runtime.native_config import Config
        reloaded = Config('PianoTeachingTask', task.default_config, folder=str(task.config.config_file.parent),
                          validator=task.config.validator)
        self.assertEqual(reloaded['Sample Interval'], 0.06)
        self.assertFalse(self.request('set-config', scope='task', id='DailyTask',
                                      values={'Manage Daily Profiles': ''})['ok'])

    def test_real_integer_dropdown_preserves_numeric_option_value(self):
        schema = self.request('get-schema')['schema']
        entry = next(task for task in schema['tasks'] if task['id'] == 'TacetTask')
        key = 'Which Tacet Suppression to Farm'
        options = entry['config_type'][key]['options']
        value, label = options[1]
        self.assertIs(type(value), int)
        self.assertIs(type(label), str)
        response = self.request('set-config', scope='task', id='TacetTask', values={key: value})
        self.assertTrue(response['ok'], response)
        task = next(task for task in self.host.tasks.values() if type(task).__name__ == 'TacetTask')
        before = task.config.config_file.read_bytes()
        self.assertEqual(json.loads(before)[key], value)
        self.assertFalse(self.request('set-config', scope='task', id='TacetTask', values={key: 9999})['ok'])
        self.assertEqual(task.config.config_file.read_bytes(), before)

    def test_paused_schema_save_and_action_defer_until_resume(self):
        from gameframe.api import Cancelled
        from gameframe.devices.replay import ReplayDevice
        host = self.host
        context = host.context
        device = ReplayDevice([ROOT / 'tests/images/weekly_boss/list1.png'])
        original_events = context.events
        context.device = device
        context.pause.set()
        schema = self.request('get-schema')['schema']
        action = next(button['action_id'] for task in schema['tasks'] if task['id'] == 'AutoAbyssTask'
                      for definition in task['config_type'].values() for button in definition.get('buttons', []))
        context.requests.put({'request_id': 'action', 'command': 'invoke-action',
                              'task_id': 'AutoAbyssTask', 'action_id': action})
        context.requests.put({'request_id': 'save', 'command': 'set-config', 'scope': 'global',
                              'id': 'Monthly Card Config', 'values': {'Monthly Card Time': 8}})
        context.requests.put({'request_id': 'schema', 'command': 'get-schema'})
        responses = []
        def events(event):
            if event['event'] != 'configuration-response':
                return
            responses.append(event)
            self.assertIsNone(host.executor._frame)
            self.assertFalse(device.actions)
            if event['request_id'] == 'schema':
                self.assertEqual([item['request_id'] for item in responses], ['save', 'schema'])
                context.pause.clear()
            elif event['request_id'] == 'action':
                context.stop.set()
        context.events = events
        try:
            with self.assertRaises(Cancelled):
                host.run_session('AutoPickTask')
            self.assertEqual([item['request_id'] for item in responses], ['save', 'schema', 'action'])
            self.assertTrue(all(item['ok'] for item in responses), responses)
        finally:
            context.events = original_events
            context.pause.clear()
            context.stop.clear()
            context.device = None
            device.close()

    def test_stopped_owner_cancels_deferred_configuration_action(self):
        from gameframe.api import Cancelled
        from gameframe.devices.replay import ReplayDevice
        context = self.host.context
        device = ReplayDevice([ROOT / 'tests/images/weekly_boss/list1.png'])
        original_events = context.events
        context.device = device
        context.pause.set()
        context.requests.put({'request_id': 'action-stop', 'command': 'invoke-action',
                              'task_id': 'AutoAbyssTask', 'action_id': 'unused'})
        context.requests.put({'request_id': 'stop-schema', 'command': 'get-schema'})
        responses = []
        def events(event):
            if event['event'] == 'configuration-response':
                responses.append(event)
                if event['request_id'] == 'stop-schema':
                    context.stop.set()
        context.events = events
        try:
            with self.assertRaises(Cancelled):
                self.host.run_session('AutoPickTask')
            action = next(item for item in responses if item['request_id'] == 'action-stop')
            self.assertFalse(action['ok'])
            self.assertEqual(action['error']['type'], 'Cancelled')
            self.assertFalse(device.actions)
        finally:
            context.events = original_events
            context.pause.clear()
            context.stop.clear()
            context.device = None
            device.close()

    def test_actions_and_service_preferences_use_real_methods(self):
        schema = self.request('get-schema')['schema']
        buttons = [(task['id'], button) for task in schema['tasks']
                   for definition in task['config_type'].values() for button in definition.get('buttons', [])]
        task, button = next(item for item in buttons if item[1]['target'] == 'owner')
        response = self.request('invoke-action', task_id=task, action_id=button['action_id'])
        self.assertTrue(response['ok'], response)
        self.assertTrue(response['result'])
        self.assertFalse(self.request('invoke-action', task_id='DailyTask', action_id=button['action_id'])['ok'])
        task, button = next(item for item in buttons if item[1]['target'] == 'management')
        response = self.request('invoke-action', task_id=task, action_id=button['action_id'])
        self.assertEqual(response['result'], {'target': 'management', 'section': 'accounts'})
        for enabled in (True, False):
            response = self.request('set-config', scope='task', id='auto-combat', values={'_enabled': enabled})
            self.assertTrue(response['ok'], response)
            combat = next(task for task in self.host.tasks.values() if type(task).__name__ == 'AutoCombatTask')
            self.assertIs(combat._manual_desired, enabled)
            self.assertIs(json.loads(combat.config.config_file.read_text())['_enabled'], enabled)
        self.assertIsNone(self.host.executor._frame)

    def test_cli_exits_and_returns_matching_ids(self):
        with tempfile.TemporaryDirectory() as root:
            from tests.fixture_support import make_account_environment
            make_account_environment(Path(root))
            result = subprocess.run([sys.executable, '-m', 'src.runtime.native_configuration',
                                     '--data-dir', root, '--version', 'test', '--manifest', str(MANIFEST)],
                                    input='{"request_id":"cli","command":"get-schema"}\n{"command":"stop"}\n',
                                    text=True, encoding='utf-8', capture_output=True, timeout=30, cwd=ROOT)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
            response = next(item for item in events if item['event'] == 'configuration-response')
            self.assertEqual(response['request_id'], 'cli')
            self.assertTrue(response['ok'], response)

    def test_cli_reports_missing_account_repository(self):
        with tempfile.TemporaryDirectory() as root:
            result = subprocess.run([sys.executable, '-m', 'src.runtime.native_configuration',
                                     '--data-dir', root, '--version', 'test', '--manifest', str(MANIFEST)],
                                    input='{"command":"stop"}\n', text=True, encoding='utf-8',
                                    capture_output=True, timeout=30, cwd=ROOT)
            self.assertEqual(result.returncode, 1)
            events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
            failure = next(item for item in events if item['event'] == 'configuration-failed')
            self.assertEqual(failure['error']['type'], 'ConfigIntegrityBlocked')


if __name__ == '__main__':
    unittest.main()
