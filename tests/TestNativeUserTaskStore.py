"""Immutable task publishing with genuine isolated native candidate processes."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.runtime.native_user_tasks import (
    NativeUserTaskStore, UserTaskConflict, UserTaskValidationError)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = '''from src.runtime.native_task import NativeBaseTask
class Example(NativeBaseTask):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = '测试用户任务'
        self.description = '合成测试'
        self.default_config = {'value': 1}
        self.support_schedule_task = True
    def run(self):
        return {'value': self.config['value']}
'''


class TestNativeUserTaskStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'private-data'
        self.store = NativeUserTaskStore(self.root)

    def test_real_validation_isolated_and_stable_identity_survives_class_rename(self):
        self.assertEqual(self.store.list(), [])
        self.assertFalse(self.root.exists())
        isolated_source = SOURCE.replace("self.description = '合成测试'", '''import os
        from src.runtime.native_config import Config
        from src.runtime.account_task_support import data_root
        from pathlib import Path
        assert data_root() == Path(Config.config_folder).parent
        self.description = str(os.getpid()) + ':' + Config.config_folder
        (Path(Config.config_folder) / 'candidate-only.json').write_text('{}')''')
        first = self.store.save(isolated_source, 'Example', required_capabilities=['capture', 'input'])
        pid, config = first['metadata']['description'].split(':', 1)
        self.assertNotEqual(int(pid), os.getpid())
        self.assertFalse(Path(config).exists())
        self.assertFalse((self.root / 'configs').exists())
        self.assertEqual(first['metadata']['id'], first['id'])
        self.assertEqual(first['kind'], 'one-shot')
        self.assertEqual(first['default_config'], {})
        self.assertEqual(first['metadata']['default_config'], {'value': 1})
        self.assertTrue(first['metadata']['support_schedule_task'])
        code_path = self.store.root / first['source_id'] / 'revisions' / first['source_revision'] / 'task.py'
        self.assertEqual(code_path.read_text(encoding='utf-8'), isolated_source)
        self.assertEqual(self.store.read(first['source_id'])['code'], isolated_source)
        renamed = SOURCE.replace('class Example(', 'class Renamed(')
        second = self.store.save(renamed, 'Renamed', source_id=first['source_id'],
                                 expected_revision=first['catalog_revision'])
        self.assertEqual(second['id'], first['id'])
        self.assertNotEqual(second['source_revision'], first['source_revision'])
        self.assertTrue(code_path.exists())
        self.assertEqual(len(self.store.list()), 1)

    def test_source_failures_do_not_publish_or_modify_existing_catalog(self):
        first = self.store.save(SOURCE, 'Example')
        before = self.store.catalog_path.read_bytes()
        candidates = (
            ('class :', 'Example'),
            ('import missing_synthetic_module', 'Example'),
            (SOURCE.replace("super().__init__(**kwargs)", "raise RuntimeError('constructor fixture')"), 'Example'),
            (SOURCE.replace("{'value': 1}", "{'value': object()}"), 'Example'),
            (SOURCE.replace("self.default_config = {'value': 1}",
                            "self.default_config = {'value': 1}; self.config_type = {'value': 'invalid'}"), 'Example'),
            ('from src.runtime.native_task import NativeBaseTask as Example', 'Example'),
            ('class Example:\n    pass\n', 'Example'),
            (SOURCE, 'Missing'),
        )
        for code, class_name in candidates:
            with self.subTest(class_name=class_name, code=code[:40]):
                with self.assertRaises(UserTaskValidationError):
                    self.store.save(code, class_name, source_id=first['source_id'],
                                    expected_revision=first['catalog_revision'])
                self.assertEqual(self.store.catalog_path.read_bytes(), before)
        self.assertFalse((self.root / 'configs').exists())

    def test_revision_conflicts_and_delete_keep_source_and_private_config(self):
        first = self.store.save(SOURCE, 'Example')
        another = NativeUserTaskStore(self.root)
        stale = another.read(first['source_id'])['catalog_revision']
        updated = self.store.save(SOURCE.replace("'value': 1", "'value': 2"), 'Example',
                                  source_id=first['source_id'], expected_revision=stale)
        before = self.store.catalog_path.read_bytes()
        with self.assertRaises(UserTaskConflict):
            another.save(SOURCE, 'Example', source_id=first['source_id'], expected_revision=stale)
        with self.assertRaises(UserTaskConflict):
            another.delete(first['source_id'], expected_revision=stale)
        with self.assertRaises(UserTaskConflict):
            another.save(SOURCE, 'Example', source_id=first['source_id'])
        self.assertEqual(self.store.catalog_path.read_bytes(), before)
        config = self.root / 'configs' / ('user_' + first['source_id'] + '.json')
        config.parent.mkdir()
        config.write_text('{"value":8}')
        revisions = self.store.root / first['source_id'] / 'revisions'
        retained = sorted(path.name for path in revisions.iterdir())
        revision = self.store.delete(first['source_id'], expected_revision=updated['catalog_revision'])
        self.assertTrue(revision)
        self.assertEqual(self.store.list(), [])
        self.assertEqual(config.read_text(), '{"value":8}')
        self.assertEqual(sorted(path.name for path in revisions.iterdir()), retained)
        with self.assertRaises(UserTaskConflict):
            self.store.read(first['source_id'])

    def test_atomic_catalog_failure_preserves_published_catalog(self):
        first = self.store.save(SOURCE, 'Example')
        before = self.store.catalog_path.read_bytes()
        real_replace = os.replace
        def fail_catalog(source, destination):
            if Path(destination) == self.store.catalog_path:
                raise OSError('atomic publish fixture')
            return real_replace(source, destination)
        with patch('src.runtime.native_user_tasks.os.replace', side_effect=fail_catalog):
            with self.assertRaisesRegex(OSError, 'atomic publish'):
                self.store.save(SOURCE.replace("'value': 1", "'value': 2"), 'Example',
                                source_id=first['source_id'], expected_revision=first['catalog_revision'])
        self.assertEqual(self.store.catalog_path.read_bytes(), before)
        self.assertFalse(list(self.store.root.glob('.catalog-*.tmp')))

    def test_load_exact_revisions_and_exports_stable_config_names(self):
        first = self.store.save(SOURCE, 'Example')
        second = self.store.save(SOURCE, 'Example', expected_revision=first['catalog_revision'])
        renamed = SOURCE.replace('class Example(', 'class Renamed(').replace("'value': 1", "'value': 2")
        updated = self.store.save(renamed, 'Renamed', source_id=first['source_id'],
                                  expected_revision=second['catalog_revision'])
        script = '''import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from src.runtime.native_user_tasks import NativeUserTaskStore
store=NativeUserTaskStore(sys.argv[2])
loaded=store.load_tasks()
assert len(loaded)==2
assert loaded[0]['task_class'].__name__=='Renamed'
assert loaded[0]['id']==sys.argv[3]
assert loaded[0]['config_name']=='user_'+loaded[0]['source_id']
assert loaded[0]['config_name']!=loaded[1]['config_name']
assert loaded[0]['source_revision']==sys.argv[4]
assert store.revision==sys.argv[5]
print('loaded-exact-revision')
'''
        result = subprocess.run([sys.executable, '-I', '-X', 'utf8', '-c', script, str(ROOT), str(self.root),
                                 first['id'], updated['source_revision'], updated['catalog_revision']],
                                capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('loaded-exact-revision', result.stdout)

    def test_modified_immutable_source_is_refused(self):
        first = self.store.save(SOURCE, 'Example')
        path = self.store.root / first['source_id'] / 'revisions' / first['source_revision'] / 'task.py'
        stamp = path.stat().st_mtime_ns
        path.write_bytes(path.read_bytes().replace(b"'value': 1", b"'value': 9"))
        os.utime(path, ns=(stamp, stamp))
        with self.assertRaisesRegex(ValueError, '已被修改'):
            self.store.read(first['source_id'])

    def test_same_source_capability_change_updates_execution_revision(self):
        first = self.store.save(SOURCE, 'Example', required_capabilities=['capture'])
        second = self.store.save(SOURCE, 'Example', source_id=first['source_id'],
                                 expected_revision=first['catalog_revision'],
                                 required_capabilities=['capture', 'input'])
        self.assertEqual(first['source_revision'], second['source_revision'])
        self.assertNotEqual(first['revision'], second['revision'])
        self.assertEqual(second['required_capabilities'], ['capture', 'input'])

    def test_real_trigger_candidate_has_service_metadata_without_live_config_writes(self):
        source = SOURCE.replace('NativeBaseTask', 'NativeTriggerTask').replace(
            "self.default_config = {'value': 1}", "self.default_config.update({'value': 1})")
        result = self.store.save(source, 'Example')
        self.assertEqual(result['kind'], 'service')
        self.assertEqual(result['default_config'], {})
        self.assertFalse(result['metadata']['default_config']['_enabled'])
        self.assertFalse((self.root / 'configs').exists())

    def test_real_processes_cannot_publish_over_the_same_expected_revision(self):
        first = self.store.save(SOURCE, 'Example')
        source = Path(self.temp.name) / 'task-source.py'
        source.write_text(SOURCE, encoding='utf-8')
        code = '''import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from src.runtime.native_user_tasks import NativeUserTaskStore,UserTaskConflict
try:
    NativeUserTaskStore(sys.argv[2]).save(Path(sys.argv[3]).read_text(encoding='utf-8'),
                                        'Example',expected_revision=sys.argv[4])
except UserTaskConflict:
    raise SystemExit(23)
'''
        command = [sys.executable, '-I', '-X', 'utf8', '-c', code, str(ROOT), str(self.root),
                   str(source), first['catalog_revision']]
        children = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, encoding='utf-8') for _ in range(2)]
        try:
            results = [child.communicate(timeout=15) for child in children]
            self.assertEqual(sorted(child.returncode for child in children), [0, 23], str(results))
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.communicate(timeout=5)
        self.assertEqual(len(self.store.list()), 2)

    def test_saved_config_and_synthetic_accounts_are_read_only_inputs_to_validation(self):
        from tests.fixture_support import make_account_environment
        make_account_environment(self.root)
        first = self.store.save(SOURCE, 'Example')
        config = self.root / 'configs' / ('user_' + first['source_id'] + '.json')
        config.write_text('{"value":7}')
        before = {path.relative_to(self.root): path.read_bytes()
                  for path in (self.root / 'configs').rglob('*') if path.is_file()}
        candidate = SOURCE + '''    def on_create(self):
        from src.account_repository import get_default_repository
        self.description = str(len(get_default_repository().list_profiles()))
        assert self.config['value'] == 7
        self.config['value'] = 8
'''
        saved = self.store.save(candidate, 'Example', source_id=first['source_id'],
                                expected_revision=first['catalog_revision'])
        self.assertEqual(saved['metadata']['description'], '3')
        self.assertEqual(saved['metadata']['current_config']['value'], 8)
        after = {path.relative_to(self.root): path.read_bytes()
                 for path in (self.root / 'configs').rglob('*') if path.is_file()}
        self.assertEqual(after, before)

    def test_runtime_defaults_preserve_saved_native_config_and_explicit_override(self):
        saved = self.store.save(SOURCE, 'Example')
        config = self.root / 'configs' / ('user_' + saved['source_id'] + '.json')
        config.parent.mkdir()
        config.write_text('{"value":7}')
        script = '''import json,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1])
from gameframe.packages import TaskDefinition
from gameframe.runtime import Runtime
from gameframe.state import RunStore
from src.runtime.native_user_tasks import NativeUserTaskStore
from src.runtime.native_combat_host import NativeCombatHost
from src.combat.settings import COMBAT_GLOBAL_DEFAULTS,TEMPLATE_MATCHING_DEFAULTS
root=Path(sys.argv[2])
store=NativeUserTaskStore(root)
descriptor=store.load_tasks()[0]
definition=TaskDefinition(descriptor['id'],descriptor['title'],descriptor['kind'],
                          descriptor['default_config'],descriptor['required_capabilities'])
manifest=SimpleNamespace(id='synthetic-native',task=lambda identifier,data: definition)
device=SimpleNamespace(capabilities=frozenset(),release_all=lambda: None)
class Package:
    def run(self,identifier,context):
        host=NativeCombatHost(context,coco_path=Path(sys.argv[1])/'assets/coco_annotations.json',
                              global_options=COMBAT_GLOBAL_DEFAULTS,ocr_engine=None,
                              template_matching=TEMPLATE_MATCHING_DEFAULTS,
                              task_entry=descriptor['task_class'],user_tasks=(descriptor,))
        assert host.task.default_config=={'value':1}
        return host.task.run()
runtime=Runtime(RunStore(root/'synthetic-run-state.json'),lambda event: None)
assert runtime.run(manifest,Package(),definition.id,device,root)=={'value':7}
config=root/'configs'/('user_'+descriptor['source_id']+'.json')
assert json.loads(config.read_text())=={'value':7}
assert runtime.run(manifest,Package(),definition.id,device,root,config={'value':9})=={'value':9}
assert json.loads(config.read_text())=={'value':9}
print('native-persisted-config-preserved')
'''
        result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', '-c', script,
                                 str(ROOT), str(self.root)],
                                capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('native-persisted-config-preserved', result.stdout)


if __name__ == '__main__':
    unittest.main()
