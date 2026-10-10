"""Installed bundle assets reach genuine native worker recognition and input."""

from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = '''from src.runtime.native_task import NativeBaseTask
class Anchor(NativeBaseTask):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = '安装包模板任务'
        self.default_config = {'Marker': 'new'}
    def on_create(self):
        assert self.group_name == '模板工具'
        assert self.import_namespace == 'tools'
        assert self.executor.feature_set.feature_exists('tools/anchor')
    def run(self):
        box = self.find_one('tools/anchor', threshold=.99)
        assert box is not None
        self.click(box)
        self.config['Marker'] = 'matched'
        return {'name': box.name, 'x': box.x, 'y': box.y,
                'group': self.group_name, 'namespace': self.import_namespace}
'''


class TestNativeUserBundleExecution(unittest.TestCase):
    def test_installed_worker_bundle_asset_reload_and_delete(self):
        from scripts.build_native_gamepack import build_native_gamepack
        from gameframe.packages import install_archive
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            installed = install_archive(build_native_gamepack(temporary / 'native.zip'), temporary / 'packages')
            output = TestAccountManagementEntry().run_probe(r'''
                import json, importlib.abc, threading, zipfile
                from unittest.mock import patch
                import numpy as np
                from PIL import Image
                class RejectOld(importlib.abc.MetaPathFinder):
                    def find_spec(self, fullname, path=None, target=None):
                        if fullname.split('.')[0] in {'ok','PySide6','qfluentwidgets','config','main'}:
                            raise AssertionError('old application imported: ' + fullname)
                sys.meta_path.insert(0, RejectOld())
                pack = Path(sys.argv[1]).parent
                version = json.loads((pack / 'manifest.json').read_text(encoding='utf-8'))['version']
                data = root / 'data'
                from src.management import AccountManagementService
                service = AccountManagementService(data, version)
                source, preview = service.preview_first_account(display_name='A1', phone='19910000001',
                    nickname='模板合成账号', sequence_ids=('序列1',))
                service.create_first_account(source, preview, confirm=True)
                from src.runtime.native_user_tasks import NativeUserTaskStore
                from src.runtime.native_user_task_bundles import FORMAT, write_index
                store = NativeUserTaskStore(data)
                def bundle(number):
                    stage = root / ('stage-' + str(number)); stage.mkdir()
                    (stage / 'assets').mkdir()
                    (stage / 'One.py').write_text(TASK_SOURCE, encoding='utf-8')
                    (stage / 'Two.py').write_text(TASK_SOURCE.replace('class Anchor(', 'class Other('), encoding='utf-8')
                    manifest = {'format': FORMAT, 'format_version': 1, 'file_name': 'tools',
                        'script_name': '模板工具', 'version': '1.0.0', 'tasks': [
                        {'key': 'one','path':'One.py','class_name':'Anchor','required_capabilities':['frames','mouse']},
                        {'key': 'two','path':'Two.py','class_name':'Other','required_capabilities':['frames','mouse']}]}
                    (stage / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
                    image = np.zeros((900,1600,3), dtype=np.uint8)
                    image[180:204,320:352] = np.random.default_rng(number).integers(20,240,(24,32,3),dtype=np.uint8)
                    Image.fromarray(image).save(stage / 'assets/image.png')
                    coco = {'images':[{'id':1,'file_name':'image.png'}], 'categories':[{'id':1,'name':'anchor'}],
                        'annotations':[{'image_id':1,'category_id':1,'bbox':[320,180,32,24]}]}
                    (stage / 'assets/coco_annotations.json').write_text(json.dumps(coco), encoding='utf-8')
                    write_index(stage)
                    archive = root / ('bundle-' + str(number) + '.okscript')
                    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as output:
                        for path in stage.rglob('*'):
                            if path.is_file(): output.write(path,path.relative_to(stage).as_posix())
                    preview = store.inspect_bundle(archive)
                    saved = store.import_bundle(archive, expected_revision=store.revision,
                        expected_archive_sha256=preview['archive_sha256'])
                    return stage, saved
                stage, saved = bundle(1)
                assert len(saved['tasks']) == 2
                selected = next(row for row in saved['tasks'] if row['bundle_task_key']=='one')
                from gameframe import worker
                from gameframe.devices.replay import ReplayDevice
                from gameframe.packages import verify_index
                device = ReplayDevice([stage / 'assets/image.png'] * 32); events=[]
                with patch.object(worker,'listen_stop',lambda *args:None), \
                        patch.object(worker,'create_device',return_value=device), \
                        patch.object(worker,'emit',events.append):
                    result = worker.main(['--package',str(pack),'--expected-version',version,
                        '--task',selected['id'],'--data-dir',str(data),
                        '--device',json.dumps({'type':'replay','frames':[]})])
                assert result == 0,(result,events)
                finished = next(event for event in events if event.get('event')=='finished')
                matched = finished['result']['business_result']
                assert matched == {'name':'tools/anchor','x':320,'y':180,'group':'模板工具','namespace':'tools'},matched
                assert any(action.kind=='button_down' for action in device.actions) and not device.held
                config = data / 'configs' / ('user_' + selected['source_id'] + '.json')
                assert json.loads(config.read_text(encoding='utf-8'))['Marker']=='matched'
                from gameframe.api import TaskContext
                from src.runtime.native_combat_host import NativeCombatHost
                from src.combat.settings import COMBAT_GLOBAL_DEFAULTS,TEMPLATE_MATCHING_DEFAULTS
                context = TaskContext(ReplayDevice([stage / 'assets/image.png'] * 4),{},data,
                    threading.Event(),'bundle-reload',lambda event:None)
                host = NativeCombatHost(context,coco_path=Path(sys.argv[1]) / 'assets/coco_annotations.json',
                    global_options=COMBAT_GLOBAL_DEFAULTS,ocr_engine=None,
                    template_matching=TEMPLATE_MATCHING_DEFAULTS,user_tasks=store.load_tasks())
                def recognize():
                    host._select_task(host._tasks_by_id()[selected['id']])
                    host.task._enabled = True
                    host.task.running = True
                    return host.task.find_one('tools/anchor',threshold=.99)
                assert recognize() is not None
                old_features = host.executor.feature_set
                stage2, updated = bundle(2)
                assert {row['id'] for row in saved['tasks']} == {row['id'] for row in updated['tasks']}
                assert [row['source_revision'] for row in saved['tasks']] == [row['source_revision'] for row in updated['tasks']]
                host.reload_user_tasks(store)
                assert host.executor.feature_set is not old_features
                context.device = ReplayDevice([stage2 / 'assets/image.png'] * 4)
                host.executor.reset_scene(check_enabled=False)
                assert recognize() is not None
                features = host.executor.feature_set; tasks = host.tasks
                descriptors = store.load_tasks()
                bad_coco = root / 'broken-coco.json'; bad_coco.write_text('{}')
                from types import SimpleNamespace
                bad = [dict(item,asset_coco_path=bad_coco) for item in descriptors]
                try: host.reload_user_tasks(SimpleNamespace(load_tasks=lambda:bad,revision='bad'))
                except KeyError: pass
                else: raise AssertionError('broken COCO committed')
                assert host.tasks is tasks and host.executor.feature_set is features
                class Broken(descriptors[0]['task_class']):
                    def __init__(self,**kwargs): raise ValueError('candidate constructor failed')
                bad = [dict(descriptors[0],task_class=Broken),descriptors[1]]
                try: host.reload_user_tasks(SimpleNamespace(load_tasks=lambda:bad,revision='bad'))
                except ValueError as error: assert 'candidate constructor failed' in str(error)
                else: raise AssertionError('broken constructor committed')
                assert host.tasks is tasks and host.executor.feature_set is features
                store.delete_bundle(saved['bundle_id'],expected_revision=store.revision)
                host.reload_user_tasks(store)
                assert selected['id'] not in host._tasks_by_id()
                assert not host.executor.feature_set.feature_exists('tools/anchor')
                verify_index(pack,required=True)
                payload = Path(sys.argv[1]).resolve()
                assert all(Path(module.__file__).resolve().is_relative_to(payload)
                    for name,module in sys.modules.items() if name.startswith('src.') and getattr(module,'__file__',None))
                print('installed-bundle-execution-pass')
            '''.replace('TASK_SOURCE',repr(SOURCE)),source_root=installed.root / 'payload',core_root=ROOT)
            self.assertIn('installed-bundle-execution-pass',output)
