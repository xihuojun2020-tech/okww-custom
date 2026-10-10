"""Two real installed workers apply user catalog revisions independently."""
from pathlib import Path
import tempfile
import unittest


SOURCE = '''from src.runtime.native_task import NativeBaseTask
class Example(NativeBaseTask):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = 'OWNER_TITLE'
    def run(self):
        return {}
'''

WORKER = '''import sys, json, importlib.abc
from pathlib import Path
from unittest.mock import patch
import threading
sys.path.insert(0, sys.argv[1])
sys.path.append(sys.argv[2])
class RejectOld(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ok','PySide6','qfluentwidgets','config','main'}:
            raise AssertionError('old application import: ' + fullname)
sys.meta_path.insert(0, RejectOld())
from gameframe import worker
from gameframe.devices.replay import ReplayDevice
from onnxocr.onnx_paddleocr import ONNXPaddleOcr
class ProbeReplay(ReplayDevice):
    def close(self):
        super().close()
        worker.emit({'event':'owner-device-closed','held':list(self.held)})
device = ProbeReplay([])
pause_received = threading.Event()
original_listener = worker.listen_stop
def listener(stop, pause, requests):
    original_set = pause.set
    def set_pause():
        original_set()
        pause_received.set()
    pause.set = set_pause
    original_listener(stop, pause, requests)
def create_device(options):
    assert pause_received.wait(10), 'initial pause not received'
    return device
with patch.object(worker, 'listen_stop', listener), patch.object(worker, 'create_device', create_device), patch('onnxocr.onnx_paddleocr.ONNXPaddleOcr', return_value=object()):
    result = worker.main(sys.argv[3:])
raise SystemExit(result)
'''


class TestNativeUserTaskOwners(unittest.TestCase):
    def test_installed_workers_reload_only_on_explicit_request(self):
        from scripts.build_native_gamepack import build_native_gamepack
        from gameframe.packages import install_archive
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            installed = install_archive(build_native_gamepack(temporary / 'native.zip'), temporary / 'packages')
            output = TestAccountManagementEntry().run_probe('''
                import json, subprocess, threading
                from queue import Queue, Empty
                from src.management import AccountManagementService
                from src.runtime.native_user_tasks import NativeUserTaskStore
                pack = Path(sys.argv[1]).parent
                version = json.loads((pack/'manifest.json').read_text())['version']
                data = root/'data'
                service = AccountManagementService(data, version)
                source, preview = service.preview_first_account(display_name='A1', phone='19910000001',
                    nickname='双owner合成账号', sequence_ids=('序列1',))
                service.create_first_account(source, preview, confirm=True)
                (data/'configs/AutoCombatTask.json').write_text(json.dumps({'_enabled':True}))
                store = NativeUserTaskStore(data)
                saved = store.save(TASK_SOURCE.replace('OWNER_TITLE','First'), 'Example')
                script = root/'owner.py'
                script.write_text(WORKER_SOURCE)
                owners = []
                def send(process, **request):
                    process.stdin.write(json.dumps(request)+'\\n')
                    process.stdin.flush()
                def wait(queue, predicate):
                    while True:
                        try: event = queue.get(timeout=15)
                        except Empty:
                            raise AssertionError(([events for process,q,events in owners if q is queue],
                                (data/'logs/ok-native.log').read_text()))
                        assert event is not None, 'worker exited before event'
                        if predicate(event): return event
                def launch(identity):
                    process = subprocess.Popen([sys.executable,'-I','-B','-X','utf8',str(script),sys.argv[1],sys.argv[3],
                        '--package',str(pack),'--task',saved['id'],'--data-dir',str(data),'--session',
                        '--device',json.dumps({'type':'replay','frames':[],'owner':identity})],
                        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                        text=True,encoding='utf-8')
                    queue, events = Queue(), []
                    def read():
                        for line in process.stdout:
                            try: event=json.loads(line)
                            except ValueError:
                                events.append({'log':line}); continue
                            events.append(event); queue.put(event)
                        queue.put(None)
                    threading.Thread(target=read,daemon=True).start()
                    owners.append((process,queue,events))
                    send(process,command='pause')
                    send(process,command='get-schema',request_id='initial')
                    return process,queue,events
                def schema(owner, request_id, expected_revision):
                    send(owner[0],command='get-schema',request_id=request_id)
                    event=wait(owner[1],lambda e:e.get('request_id')==request_id)
                    assert event['ok'], event
                    assert event['applied_revision']==expected_revision, event
                    return next(t for t in event['schema']['tasks'] if t['id']==saved['id'])['name']
                try:
                    first = launch('a')
                    for identity in ('a','b'):
                        owner = first if identity=='a' else launch('b')
                        event=wait(owner[1],lambda e:e.get('request_id')=='initial')
                        assert event['ok'], event
                        assert event['applied_revision']==store.revision, event
                        assert next(t for t in event['schema']['tasks'] if t['id']==saved['id'])['name']=='First'
                    second = owners[1]
                    old=store.revision
                    latest=store.read(saved['source_id'])
                    store.save(TASK_SOURCE.replace('OWNER_TITLE','Second'),'Example',source_id=saved['source_id'],
                        expected_revision=latest['catalog_revision'])
                    new=store.revision
                    assert old!=new
                    send(first[0],command='reload-user-tasks')
                    applied=wait(first[1],lambda e:e.get('event')=='user-tasks-reloaded')
                    assert applied['applied_revision']==new, applied
                    assert schema(first,'first-after',new)=='Second'
                    assert schema(second,'second-before',old)=='First'
                    assert not any(e.get('event')=='user-tasks-reloaded' for e in second[2])
                    send(second[0],command='reload-user-tasks')
                    applied=wait(second[1],lambda e:e.get('event')=='user-tasks-reloaded')
                    assert applied['applied_revision']==new, applied
                    assert schema(second,'second-after',new)=='Second'
                finally:
                    for process,queue,events in owners:
                        if process.poll() is None: send(process,command='stop')
                    for process,queue,events in owners:
                        assert process.wait(timeout=15)==130, events
                        while not any(e.get('event')=='owner-device-closed' for e in events):
                            wait(queue,lambda e:e.get('event')=='owner-device-closed')
                        assert next(e for e in events if e.get('event')=='owner-device-closed')['held']==[]
                        process.stdin.close(); process.stdout.close()
                assert json.loads((data/'configs/AutoCombatTask.json').read_text())['_enabled'] is True
                print('native-user-owner-isolation-pass')
            '''.replace('TASK_SOURCE', repr(SOURCE)).replace('WORKER_SOURCE', repr(WORKER)),
                source_root=installed.root / 'payload', core_root=Path(__file__).resolve().parents[1])
            self.assertIn('native-user-owner-isolation-pass', output)
