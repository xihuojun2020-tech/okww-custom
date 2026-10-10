"""Installed native worker executes the exact user definition checked by core."""

from pathlib import Path
import tempfile
import unittest


SOURCE = '''from src.runtime.native_task import NativeBaseTask
class Example(NativeBaseTask):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = '离线用户执行任务'
        self.default_config = {'Value': 'stable-user'}
    def run(self):
        self.click(.5, .5)
        return {'marker': self.config['Value']}
class Other(Example):
    pass
'''


class TestNativeUserTaskExecution(unittest.TestCase):
    def probe(self, *, change_definition=False, override=False):
        from scripts.build_native_gamepack import build_native_gamepack
        from gameframe.packages import install_archive
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            installed = install_archive(build_native_gamepack(temporary / 'native.zip'), temporary / 'packages')
            return TestAccountManagementEntry().run_probe('''
                import json, importlib.abc
                from unittest.mock import patch
                class RejectOld(importlib.abc.MetaPathFinder):
                    def find_spec(self, fullname, path=None, target=None):
                        if fullname.split('.')[0] in {'ok','PySide6','qfluentwidgets','config','main'}:
                            raise AssertionError('worker imported old application: ' + fullname)
                sys.meta_path.insert(0, RejectOld())
                pack = Path(sys.argv[1]).parent
                version = json.loads((pack / 'manifest.json').read_text(encoding='utf-8'))['version']
                from src.management import AccountManagementService
                service = AccountManagementService(root / 'data', version)
                source, preview = service.preview_first_account(display_name='A1', phone='19910000001',
                    nickname='用户执行合成账号', sequence_ids=('序列1',))
                service.create_first_account(source, preview, confirm=True)
                from src.runtime.native_user_tasks import NativeUserTaskStore
                store = NativeUserTaskStore(root / 'data')
                code = TASK_SOURCE
                saved = store.save(code, 'Example', required_capabilities=['frames','mouse'])
                settings = root / 'data/configs' / ('user_' + saved['source_id'] + '.json')
                settings.write_text(json.dumps({'Value':'saved-user'}), encoding='utf-8')
                from gameframe import worker
                from gameframe.devices.replay import ReplayDevice
                from gameframe.packages import verify_index
                device = ReplayDevice([Path(FRAME_PATH)] * 32)
                events = []
                original_load = NativeUserTaskStore.load_tasks
                def load_tasks(current):
                    if CHANGE_DEFINITION:
                        latest = current.read(saved['source_id'])
                        current.save(code, 'Other', source_id=saved['source_id'],
                            expected_revision=latest['catalog_revision'], required_capabilities=['frames','mouse'])
                    return original_load(current)
                with patch.object(worker, 'listen_stop', lambda *args: None), \\
                        patch.object(worker, 'create_device', return_value=device), \\
                        patch.object(worker, 'emit', events.append), \\
                        patch.object(NativeUserTaskStore, 'load_tasks', load_tasks):
                    result = worker.main(['--package', str(pack), '--expected-version', version,
                        '--task', saved['id'], '--data-dir', str(root / 'data'),
                        '--device', json.dumps({'type':'replay','frames':[]}),
                        '--config', json.dumps({'Value':'run-override'} if OVERRIDE else {})])
                if CHANGE_DEFINITION:
                    assert result == 1 and not device.actions, (result, events, device.actions)
                    assert any('definition changed' in event.get('error','') for event in events), events
                else:
                    assert result == 0 and device.actions and not device.held, (result, events, device.actions)
                    finished = next(event for event in events if event.get('event') == 'finished')
                    assert finished['status'] == 'success'
                    assert finished['result']['business_result'] == {
                        'marker':'run-override' if OVERRIDE else 'saved-user'}
                verify_index(pack, required=True)
                payload = Path(sys.argv[1]).resolve()
                assert all(Path(module.__file__).resolve().is_relative_to(payload)
                    for name, module in sys.modules.items() if name.startswith('src.') and getattr(module,'__file__',None))
                print('native-user-definition-pass')
            '''.replace('CHANGE_DEFINITION', repr(change_definition)).replace('TASK_SOURCE', repr(SOURCE))
                .replace('OVERRIDE', repr(override)).replace('FRAME_PATH', repr(str(
                    Path(__file__).resolve().parents[1] / 'tests/images/in_combat.png'))),
                source_root=installed.root / 'payload', core_root=Path(__file__).resolve().parents[1])

    def test_installed_worker_runs_user_task(self):
        self.assertIn('native-user-definition-pass', self.probe())

    def test_published_new_export_is_rejected_before_input(self):
        self.assertIn('native-user-definition-pass', self.probe(change_definition=True))

    def test_explicit_config_overrides_saved_user_config(self):
        self.assertIn('native-user-definition-pass', self.probe(override=True))


if __name__ == '__main__':
    unittest.main()
