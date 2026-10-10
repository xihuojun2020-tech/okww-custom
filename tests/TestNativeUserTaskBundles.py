"""Real isolated native bundles, explicit source migration and atomic group publishing."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image

from src.runtime.native_user_task_bundles import FORMAT, transform_legacy, write_index
from src.runtime.native_user_tasks import NativeUserTaskStore, UserTaskConflict, UserTaskValidationError


ROOT = Path(__file__).resolve().parents[1]
SOURCE = '''from src.runtime.combat_api import BaseTask
class Example(BaseTask):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = '包任务'
        self.description = '合成包验证'
        self.default_config = {'value': 1}
    def run(self):
        return {'value': self.config['value']}
'''


class TestNativeUserTaskBundles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.store = NativeUserTaskStore(self.data)
        self.counter = 0

    def archive(self, *, sources=None, tasks=None, file_name='tools', legacy=False,
                assets=True, pixel=30, coco_edit=None, indexed=True):
        self.counter += 1
        stage = self.root / ('archive-stage-' + str(self.counter))
        stage.mkdir()
        sources = sources or {'One.py': SOURCE, 'Two.py': SOURCE.replace('Example', 'Another')}
        for path, code in sources.items():
            target = stage / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code, encoding='utf-8', newline='')
        manifest = {'file_name': file_name, 'script_name': '工具分组', 'version': '1.0.0'}
        if not legacy:
            manifest.update(format=FORMAT, format_version=1, tasks=(tasks if tasks is not None else [
                {'key': 'one', 'path': 'One.py', 'class_name': 'Example', 'required_capabilities': []},
                {'key': 'two', 'path': 'Two.py', 'class_name': 'Another', 'required_capabilities': []}]))
        (stage / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
        if assets:
            (stage / 'assets').mkdir()
            Image.new('RGB', (16, 16), (pixel, 50, 80)).save(stage / 'assets/image.png')
            coco = {'images': [{'id': 1, 'file_name': 'image.png'}],
                    'categories': [{'id': 1, 'name': 'anchor'}],
                    'annotations': [{'image_id': 1, 'category_id': 1, 'bbox': [0, 0, 8, 8]}]}
            if coco_edit:
                coco_edit(coco)
            (stage / 'assets/coco_annotations.json').write_text(json.dumps(coco), encoding='utf-8')
        if not legacy and indexed:
            write_index(stage)
        output = self.root / ('input-' + str(self.counter) + '.okscript')
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in stage.rglob('*'):
                if path.is_file():
                    archive.write(path, path.relative_to(stage).as_posix())
        return output

    def publish(self, archive, **values):
        preview = self.store.inspect_bundle(archive)
        self.store.list()
        return self.store.import_bundle(archive, expected_revision=self.store.revision,
                                        expected_archive_sha256=preview['archive_sha256'], **values)

    def child(self, script, *arguments):
        result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', '-c', script,
                                 str(ROOT), str(self.data), *map(str, arguments)],
                                capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_inspection_never_executes_source_and_locks_archive_bytes(self):
        archive = self.archive(sources={'One.py': "raise RuntimeError('must not inspect by execution')\n"},
                               tasks=[{'key': 'one', 'path': 'One.py', 'class_name': 'Example',
                                       'required_capabilities': []}])
        preview = self.store.inspect_bundle(archive)
        self.assertEqual(preview['format'], 'native')
        self.assertEqual(preview['code_diffs'], [])
        self.assertFalse(self.data.exists())
        archive.write_bytes(archive.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'changed after preview'):
            self.store.import_bundle(archive, expected_revision=self.store.revision,
                                     expected_archive_sha256=preview['archive_sha256'])
        self.assertFalse(self.store.catalog_path.exists())

    def test_real_multi_source_update_preserves_ids_configs_and_assets_revision(self):
        first_archive = self.archive()
        original = first_archive.read_bytes()
        first = self.publish(first_archive)
        self.assertEqual(len(first['tasks']), 2)
        row = first['tasks'][0]
        self.assertEqual(row['default_config'], {})
        self.assertEqual(row['metadata']['default_config'], {'value': 1})
        config = self.data / 'configs' / ('user_' + row['source_id'] + '.json')
        config.parent.mkdir()
        config.write_text('{"value":7}')
        unchanged = config.read_bytes()
        second = self.publish(self.archive(pixel=90))
        self.assertEqual(first['bundle_id'], second['bundle_id'])
        self.assertEqual([task['id'] for task in first['tasks']], [task['id'] for task in second['tasks']])
        self.assertEqual(row['source_revision'], second['tasks'][0]['source_revision'])
        self.assertNotEqual(row['bundle_revision'], second['tasks'][0]['bundle_revision'])
        self.assertNotEqual(row['revision'], second['tasks'][0]['revision'])
        self.assertEqual(second['tasks'][0]['metadata']['current_config']['value'], 7)
        self.assertEqual(config.read_bytes(), unchanged)
        declarations = [{'key': 'one', 'path': 'Renamed.py', 'class_name': 'Renamed', 'required_capabilities': []}]
        third = self.publish(self.archive(sources={'Renamed.py': SOURCE.replace('Example', 'Renamed')},
                                          tasks=declarations))
        self.assertEqual(third['tasks'][0]['id'], row['id'])
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(self.store.read(row['source_id'])['class_name'], 'Renamed')
        self.assertEqual(config.read_bytes(), unchanged)
        self.assertEqual(first_archive.read_bytes(), original)
        self.child('''import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from src.runtime.native_user_tasks import NativeUserTaskStore
store=NativeUserTaskStore(sys.argv[2])
loaded=store.load_tasks()
assert len(loaded)==1 and loaded[0]['task_class'].__name__=='Renamed'
assert loaded[0]['asset_coco_path'].is_absolute()
assert loaded[0]['asset_namespace']=='tools'
assert loaded[0]['group_name']=='工具分组'
assert loaded[0]['config_name']=='user_'+loaded[0]['source_id']
assert loaded[0]['bundle_revision']==sys.argv[3]
''', third['tasks'][0]['bundle_revision'])

    def test_two_exports_from_one_module_execute_module_once(self):
        source = SOURCE + '''created=[]
class First(Example):
    def on_create(self):
        created.append(self.native_task_id)
class Second(Example):
    def on_create(self):
        assert len(created)==1, 'source must execute once for both exports'
'''
        tasks = [{'key': key, 'path': 'Shared.py', 'class_name': name, 'required_capabilities': []}
                 for key, name in [('first', 'First'), ('second', 'Second')]]
        result = self.publish(self.archive(sources={'Shared.py': source}, tasks=tasks, assets=False))
        self.assertEqual(len(result['tasks']), 2)
        self.assertEqual(result['tasks'][0]['source_revision'], result['tasks'][1]['source_revision'])
        self.assertNotEqual(result['tasks'][0]['id'], result['tasks'][1]['id'])

    def test_invalid_whole_bundle_preserves_exact_catalog_and_atomic_failure(self):
        first = self.publish(self.archive())
        before = self.store.catalog_path.read_bytes()
        candidates = [
            self.archive(sources={'One.py': SOURCE, 'Two.py': SOURCE.replace('Example', 'Another').replace(
                "super().__init__(**kwargs)", "raise RuntimeError('second candidate failure')")}),
            self.archive(indexed=False),
            self.archive(coco_edit=lambda data: data['images'][0].update(file_name='../outside.png')),
            self.archive(coco_edit=lambda data: data['annotations'][0].update(category_id=99)),
            self.archive(sources={'One.py': SOURCE + '''    def on_create(self):
        from pathlib import Path
        (Path(__file__).parent / 'assets/image.png').write_bytes(b'changed during validation')
''', 'Two.py': SOURCE.replace('Example', 'Another')}),
        ]
        for archive in candidates:
            with self.subTest(archive=archive.name), self.assertRaises((ValueError, UserTaskValidationError)):
                self.publish(archive)
            self.assertEqual(self.store.catalog_path.read_bytes(), before)
        preview_archive = self.archive(pixel=70)
        preview = self.store.inspect_bundle(preview_archive)
        real_replace = os.replace
        def fail_catalog(source, destination):
            if Path(destination) == self.store.catalog_path:
                raise OSError('bundle publish failure')
            return real_replace(source, destination)
        with patch('src.runtime.native_user_tasks.os.replace', side_effect=fail_catalog):
            with self.assertRaisesRegex(OSError, 'bundle publish failure'):
                self.store.import_bundle(preview_archive, expected_revision=first['catalog_revision'],
                                         expected_archive_sha256=preview['archive_sha256'])
        self.assertEqual(self.store.catalog_path.read_bytes(), before)
        self.assertFalse(list(self.store.root.glob('.catalog-*.tmp')))

    def test_legacy_ast_conversion_is_reviewable_exact_and_requires_confirmation(self):
        legacy = SOURCE.replace('from src.runtime.combat_api import BaseTask',
                                '# 保留注释\n"中文"; from ok import BaseTask as TaskBase, Box, Logger\n'
                                'from ok.task.exceptions import WaitFailedException\n').replace('Example(BaseTask)', 'Example(TaskBase)')
        archive = self.archive(sources={'One.py': legacy}, legacy=True)
        before = archive.read_bytes()
        preview = self.store.inspect_bundle(archive)
        self.assertEqual(preview['format'], 'legacy')
        self.assertEqual(preview['tasks'][0]['class_name'], 'Example')
        self.assertEqual(preview['errors'], [])
        difference = preview['code_diffs'][0]
        self.assertIn('# 保留注释', difference['code'])
        self.assertIn('BaseTask as TaskBase, Box, Logger', difference['code'])
        self.assertIn('from src.runtime.combat_api import WaitFailedException', difference['code'])
        self.assertIn('--- One.py', difference['diff'])
        with self.assertRaisesRegex(ValueError, 'explicit tasks'):
            self.store.import_bundle(archive, expected_revision=self.store.revision,
                                     expected_archive_sha256=preview['archive_sha256'])
        declarations = deepcopy(preview['tasks'])
        declarations[0]['required_capabilities'] = []
        saved = self.publish(archive, migration_tasks=declarations)
        self.assertEqual(self.store.read(saved['tasks'][0]['source_id'])['code'], difference['code'])
        self.assertEqual(archive.read_bytes(), before)
        bad_imports = ['from ok import og', 'from ok import *', 'import ok',
                       'from ok.gui.Communicate import communicate', "__import__('ok')",
                       'from ok import BaseScene', 'from ok import get_bounding_box', 'from Two import Another']
        for bad in bad_imports:
            with self.subTest(bad=bad):
                _, errors, _ = transform_legacy(legacy + '\n' + bad + '\n', 'One.py', {'One', 'Two'})
                self.assertTrue(errors)
        bad_archive = self.archive(sources={'One.py': legacy + '\nfrom ok import og\n'}, legacy=True)
        bad_bytes = bad_archive.read_bytes()
        before_catalog = self.store.catalog_path.read_bytes()
        bad_preview = self.store.inspect_bundle(bad_archive)
        self.assertTrue(bad_preview['errors'])
        with self.assertRaisesRegex(ValueError, 'Unsupported legacy import'):
            self.store.import_bundle(bad_archive, expected_revision=self.store.revision,
                                     expected_archive_sha256=bad_preview['archive_sha256'],
                                     migration_tasks=declarations)
        self.assertEqual(self.store.catalog_path.read_bytes(), before_catalog)
        self.assertEqual(bad_archive.read_bytes(), bad_bytes)

    def test_archive_external_paths_duplicates_and_symlinks_are_refused(self):
        for name, symlink in [('../escape.py', False), ('/absolute.py', False),
                              ('C:/escape.py', False), ('folder\\task.py', False), ('linked.py', True)]:
            archive = self.root / 'unsafe.okscript'
            with zipfile.ZipFile(archive, 'w') as output:
                member = zipfile.ZipInfo(name)
                if symlink:
                    member.create_system = 3
                    member.external_attr = 0o120777 << 16
                output.writestr(member, b'outside')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.store.inspect_bundle(archive)
        archive = self.root / 'duplicate.okscript'
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('manifest.json', '{}')
            with self.assertWarns(UserWarning):
                output.writestr('manifest.json', '{}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.store.inspect_bundle(archive)

    def test_export_reimport_group_delete_preserves_private_config_and_ids(self):
        first = self.publish(self.archive())
        row = first['tasks'][0]
        config = self.data / 'configs' / ('user_' + row['source_id'] + '.json')
        config.parent.mkdir()
        config.write_text('{"value":8}')
        export = self.root / 'exported.okscript'
        result = self.store.export_bundle(first['bundle_id'], export, expected_revision=first['catalog_revision'])
        self.assertEqual(result['archive_sha256'], hashlib.sha256(export.read_bytes()).hexdigest())
        with zipfile.ZipFile(export) as archive:
            self.assertFalse(any(name.startswith('configs/') for name in archive.namelist()))
            self.assertIn('assets/image.png', archive.namelist())
        with self.assertRaises(FileExistsError):
            self.store.export_bundle(first['bundle_id'], export, expected_revision=first['catalog_revision'])
        with self.assertRaises(UserTaskConflict):
            self.store.delete(row['source_id'], expected_revision=first['catalog_revision'])
        read = self.store.read_bundle(first['bundle_id'])
        self.assertEqual(read, self.store.list_bundles()[0])
        deleted = self.store.delete_bundle(first['bundle_id'], expected_revision=first['catalog_revision'])
        self.assertEqual(deleted['tasks'], [])
        self.assertEqual(self.store.list(), [])
        self.assertEqual(config.read_text(), '{"value":8}')
        restored = self.publish(export)
        self.assertEqual([item['id'] for item in first['tasks']], [item['id'] for item in restored['tasks']])
        self.assertEqual(restored['tasks'][0]['metadata']['current_config']['value'], 8)
        fresh = NativeUserTaskStore(self.root / 'fresh-data')
        preview = fresh.inspect_bundle(export)
        imported = fresh.import_bundle(export, expected_revision=fresh.revision,
                                       expected_archive_sha256=preview['archive_sha256'])
        self.assertEqual(imported['tasks'][0]['metadata']['current_config']['value'], 1)

    def test_export_selected_standalone_tasks_does_not_include_configs(self):
        first = self.store.save(SOURCE, 'Example')
        second = self.store.save(SOURCE, 'Example')
        exported = self.root / 'authored.okscript'
        self.store.export_tasks([first['source_id'], second['source_id']], exported,
                                file_name='authored', script_name='作者任务', version='1.0.0',
                                expected_revision=second['catalog_revision'])
        preview = self.store.inspect_bundle(exported)
        self.assertEqual(len(preview['tasks']), 2)
        self.assertNotEqual(preview['tasks'][0]['path'], preview['tasks'][1]['path'])
        self.assertEqual({item['key'] for item in preview['tasks']}, {first['source_id'], second['source_id']})
        self.assertFalse(any(name.startswith('configs') for name in preview['files']))
        with self.assertRaises(UserTaskConflict):
            self.store.export_tasks([first['source_id']], self.root / 'stale.okscript',
                                    file_name='stale', script_name='stale', version='1',
                                    expected_revision=first['catalog_revision'])

    def test_snapshot_asset_mutation_is_refused_before_user_code_load(self):
        saved = self.publish(self.archive())
        row = saved['tasks'][0]
        path = self.store.root / 'bundles' / saved['bundle_id'] / 'revisions' / row['bundle_revision'] / 'assets/image.png'
        Image.new('RGB', (16, 16), (150, 10, 20)).save(path)
        self.child('''import sys
sys.path.insert(0,sys.argv[1])
from src.runtime.native_user_tasks import NativeUserTaskStore
try:
    NativeUserTaskStore(sys.argv[2]).load_tasks()
except ValueError as error:
    assert 'SHA256' in str(error)
else:
    raise AssertionError('mutated assets must not load')
''')

    def test_real_bundle_writers_publish_only_one_complete_group(self):
        existing = self.store.save(SOURCE, 'Example')
        archive = self.archive(assets=False)
        preview = self.store.inspect_bundle(archive)
        script = '''import sys
sys.path.insert(0,sys.argv[1])
from src.runtime.native_user_tasks import NativeUserTaskStore,UserTaskConflict
try:
    NativeUserTaskStore(sys.argv[2]).import_bundle(sys.argv[3],expected_revision=sys.argv[4],
                                                 expected_archive_sha256=sys.argv[5])
except UserTaskConflict:
    raise SystemExit(23)
'''
        command = [sys.executable, '-I', '-B', '-X', 'utf8', '-c', script, str(ROOT), str(self.data),
                   str(archive), existing['catalog_revision'], preview['archive_sha256']]
        children = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, encoding='utf-8') for _ in range(2)]
        try:
            results = [child.communicate(timeout=20) for child in children]
            self.assertEqual(sorted(child.returncode for child in children), [0, 23], str(results))
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.communicate(timeout=5)
        rows = self.store.list()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['id'], existing['id'])
        self.assertEqual(len(self.store.list_bundles()), 1)
        self.assertEqual(len(self.store.list_bundles()[0]['tasks']), 2)

    def test_real_validation_on_create_sees_complete_namespaced_assets_and_config_isolation(self):
        source = SOURCE + '''    def on_create(self):
        import os
        from pathlib import Path
        assert self.group_name == '工具分组'
        assert self.executor.feature_set.feature_exists('tools/anchor')
        coco=[item for item in self.executor.feature_set._coco_sources if item[1]=='tools'][0]
        assert Path(coco[0]).parent.joinpath('image.png').is_file()
        self.description=str(os.getpid())
'''
        tasks = [{'key': 'one', 'path': 'One.py', 'class_name': 'Example', 'required_capabilities': []}]
        saved = self.publish(self.archive(sources={'One.py': source}, tasks=tasks))
        self.assertNotEqual(int(saved['tasks'][0]['metadata']['description']), os.getpid())
        self.assertFalse((self.data / 'configs').exists())
        self.assertEqual(saved['tasks'][0]['metadata']['group_name'], '工具分组')

    def test_legacy_chinese_logical_name_preserves_namespace_and_stable_identity(self):
        legacy = SOURCE.replace('from src.runtime.combat_api import BaseTask', 'from ok import BaseTask')
        archive = self.archive(sources={'One.py': legacy}, legacy=True, file_name='每日工具')
        preview = self.store.inspect_bundle(archive)
        declarations = deepcopy(preview['tasks'])
        declarations[0]['required_capabilities'] = []
        saved = self.publish(archive, migration_tasks=declarations)
        self.assertEqual(saved['tasks'][0]['asset_namespace'], '每日工具')
        again = self.publish(archive, migration_tasks=declarations)
        self.assertEqual(saved['tasks'][0]['id'], again['tasks'][0]['id'])

    def test_legacy_import_target_rewrite_preserves_crlf_comments_and_aliases(self):
        original = ('# 中文注释\r\n"中文"; from ok import (\r\n'
                    '    BaseTask as BT,  # 基类别名\r\n    Logger,\r\n)\r\n'
                    'class Example(BT):\r\n    pass\r\n')
        converted, errors, classes = transform_legacy(original, 'One.py')
        self.assertEqual(errors, [])
        self.assertEqual(classes, ['Example'])
        self.assertEqual(converted['code'], original.replace('from ok import', 'from src.runtime.combat_api import'))


if __name__ == '__main__':
    unittest.main()
