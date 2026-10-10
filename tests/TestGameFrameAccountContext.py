"""Offscreen context routing and actual configuration JSONL, without devices."""
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class TestGameFrameAccountContext(unittest.TestCase):
    def setUp(self):
        from tests.TestGameFrameDesktopControls import TestGameFrameDesktopControls
        self.fixture = TestGameFrameDesktopControls()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.window = self.fixture.window
        self.window.restore_services.setChecked(False)
        self.window.packages = tuple(replace(item, configuration=True, supports_session=True)
                                     if item.id == 'native' else item for item in self.window.packages)
        self.manifest = self.window._manifest()
        self.manifest.root.joinpath('entry.py').write_text('''
import os,sys
from pathlib import Path
class Package:
    def configuration_command(self,data):
        return {'command':[sys.executable,'-u',str(Path(__file__).with_name('context_child.py')),str(data)],
                'cwd':str(Path(__file__).parent),'env':dict(os.environ)}
''', encoding='utf-8')
        self.manifest.root.joinpath('context_child.py').write_text('''
import json,sys
from pathlib import Path
data=Path(sys.argv[1]);data.mkdir(parents=True,exist_ok=True)
path=data/'context.json'
value=json.loads(path.read_text()) if path.exists() else {'sequence':'S1','account':'A1'}
for line in sys.stdin:
    request=json.loads(line)
    if request['command']=='stop':break
    if request['command']=='set-context':
        value.update({k:request[k] for k in ('sequence','account') if k in request})
        path.write_text(json.dumps(value))
    context=dict(value,available=True,readonly=False,reason='',summary='fixture context',
        sequences=[{'value':'S1','label':'S1'}],accounts=[{'value':x,'label':x} for x in ('A1','A3')],
        verified_account=None)
    print(json.dumps({'event':'configuration-response','ok':True,'result':context,'schema':{'tasks':[]}}),flush=True)
''', encoding='utf-8')

    def query(self, command='get-context', **values):
        window = self.window
        window._query_account_context(command, **values)
        self.assertTrue(window._configuration_querying)
        # Join without pumping Qt: completion must be queued only after owner cleanup.
        window._configuration_thread.join(10)
        self.assertFalse(window._configuration_thread.is_alive())
        self.assertTrue(window._configuration_querying)
        self.assertIsNotNone(window.configuration_controller.process.returncode)
        self.assertTrue(window.configuration_controller.process.stdout.closed)
        window._drain_events()
        self.assertFalse(window._configuration_querying)

    def test_real_configuration_child_get_set_and_owner_cleanup_before_ui(self):
        window = self.window
        restored = []
        def restored_session():
            self.assertFalse(window._configuration_querying)
            self.assertTrue(window.configuration_controller.process.stdout.closed)
            restored.append(True)
        window._restore_pending = True
        with patch.object(window, 'start_session', side_effect=restored_session):
            self.query()
        self.assertEqual(restored, [True])
        self.assertFalse(window._restore_pending)
        self.assertEqual(self.window.account_select.currentData(), 'A1')
        self.query('set-context', account='A3')
        path = self.window.data_dir / 'native/context.json'
        self.assertEqual(json.loads(path.read_text())['account'], 'A3')
        self.query()
        self.assertEqual(self.window.account_select.currentData(), 'A3')
        self.assertEqual(self.fixture.fixture.controller.starts, [])

    def test_query_locks_root_and_package_until_result_applied(self):
        window = self.window
        original = window.data_dir
        window._query_account_context('get-context')
        window._drain_events()
        # If already completed, restart a query while its result remains queued.
        if not window._configuration_querying:
            window._query_account_context('get-context')
        window._configuration_thread.join(10)
        self.assertTrue(window._configuration_querying)
        self.assertFalse(window.package_select.isEnabled())
        with patch('gameframe.gui.QFileDialog.getExistingDirectory',
                   side_effect=AssertionError('root dialog must stay locked')):
            window.choose_data_root()
        self.assertEqual(window.data_dir, original)
        window._drain_events()
        self.assertFalse(window._configuration_querying)
        self.assertTrue(window.package_select.isEnabled())
        new_root = original.parent / 'another-user-root'
        new_root.mkdir()
        with patch('gameframe.gui.QFileDialog.getExistingDirectory', return_value=str(new_root)):
            window.choose_data_root()
        self.assertEqual(window.data_dir, new_root.resolve())
        self.assertIsNone(window._account_context)
        window._drain_events()
        self.assertIsNone(window._account_context)

    def test_live_route_and_foreground_request_freezes_context(self):
        self.query()
        window = self.window
        calls = []
        window.controller.session = True
        window.controller.request_live = lambda command, request_id, **values: calls.append((command, request_id, values))
        window.process = SimpleNamespace(poll=lambda: None)
        self.addCleanup(setattr, window, 'process', None)
        window.refresh_account_context()
        self.assertEqual(calls[0][0], 'get-context')
        self.assertEqual(window._live_routes[calls[0][1]], 'account-context')
        response = dict(event='configuration-response', request_id=calls[0][1], ok=True,
                        result=window._account_context, schema={'tasks': []})
        self.assertTrue(window._live_response(response))
        self.assertEqual(window._live_routes, {})
        window.device_edit.setPlainText('{"type":"replay","frames":[]}')
        window.start_selected()
        self.assertTrue(window._foreground_requested)
        window._drain_events()
        self.assertFalse(window.sequence_select.isEnabled())
        self.assertFalse(window.account_select.isEnabled())
        self.assertFalse(window.context_refresh_button.isEnabled())
        window.refresh_account_context()
        self.assertEqual(len(calls), 1)
        window._pause_status(json.dumps({'event':'session-task-failed','task_id':'task','error':'fixture'}))
        self.assertFalse(window._foreground_requested)
        self.assertEqual(len(calls), 2)

    def test_categories_keep_stable_id_hide_tasks_and_failed_restore_preflight(self):
        window = self.window
        task = window._all_tasks[0]
        tasks = (replace(task, id='first', category='daily', order=0),
                 replace(task, id='stable', category='daily', order=1),
                 replace(task, id='hidden', category='daily', visible=False, order=2),
                 replace(task, id='weekly', category='weekly', order=3))
        manifest = replace(self.manifest, tasks=tasks)
        window.packages = tuple(manifest if item.id == 'native' else item for item in window.packages)
        window._select_package(window.package_select.currentIndex())
        self.assertNotIn('hidden', [item.id for item in window._visible_tasks])
        window.task_list.setCurrentRow(1)
        window.category_select.setCurrentIndex(window.category_select.findData('daily'))
        self.assertEqual(window._visible_tasks[window.task_list.currentRow()].id, 'stable')
        window._task_titles['stable'] = 'Translated title'
        window._fill_tasks()
        self.assertEqual(window._visible_tasks[window.task_list.currentRow()].id, 'stable')
        self.assertIn('Translated title', window.task_list.currentItem().text())
        window._restore_pending = True
        window._configuration_querying = True
        window._events.put(('account-context', {'ok':False,'error':{'message':'preflight rejected'}}))
        with patch.object(window, 'start_session', side_effect=AssertionError('failed preflight must not start')):
            window._drain_events()
        self.assertFalse(window._restore_pending)
        self.assertFalse(window._configuration_querying)
        window._restore_pending = True
        window._configuration_querying = True
        window._events.put(('context-error', RuntimeError('child failed')))
        with patch.object(window, 'start_session', side_effect=AssertionError('failed child must not start')):
            window._drain_events()
        self.assertFalse(window._restore_pending)
        self.assertFalse(window._configuration_querying)


class TestGameFrameProductionContextChild(unittest.TestCase):
    def test_production_configuration_command_jsonl_selection_saved(self):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        TestAccountManagementEntry().run_probe('''
            import json
            from tests.fixture_support import make_account_environment
            from gameframe.controller import Controller
            from gameframe.packages import PackageManifest
            data=root/'data';make_account_environment(data)
            (data/'configs').mkdir(exist_ok=True)
            (data/'configs/Language.json').write_text('{"Language":"en_US"}')
            manifest=PackageManifest.read(Path(sys.argv[1])/'gamepacks/wuthering_waves_native')
            controller=Controller()
            try:
                process=controller.start_configuration(manifest,data_dir=data)
                requests=[{'command':'set-context','sequence':'S1','account':'A3','request_id':'set'},
                          {'command':'get-context','request_id':'get'}]
                output,_=process.communicate(''.join(json.dumps(item)+'\\n' for item in requests),timeout=25)
                assert process.returncode==0,output
                responses=[json.loads(line) for line in output.splitlines() if line.startswith('{')]
                responses=[item for item in responses if item.get('event')=='configuration-response']
                assert len(responses)==2 and all(item['ok'] for item in responses),output
                assert responses[-1]['result']['saved_account']=='A3',output
                stored=json.loads((data/'configs/MultiAccountDailyTask.json').read_text(encoding='utf-8'))
                assert stored['当前执行账号']=='A3' and stored['当前序列']=='S1',stored
                assert not (data/'runs.sqlite').exists()
            finally:controller.close()
        ''')
