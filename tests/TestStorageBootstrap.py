import json
import sqlite3
import tempfile
import subprocess
import sys
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from src.runtime import storage_bootstrap as storage


class TestStorageBootstrap(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        self.target = self.base / 'data'
        self.sources = {kind: {'source': str(self.base / 'old' / kind), 'history': []}
                        for kind in storage.KINDS if kind not in ('logs', 'cache')}
        self.sources.update({k: {'source': str(self.repo / k), 'history': []} for k in ('logs', 'cache')})
        for value in self.sources.values(): Path(value['source']).mkdir(parents=True)
        self.patch = patch.object(storage, 'discover', return_value=self.sources)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def source(self, kind, name):
        return Path(self.sources[kind]['source']) / name

    def test_copy_originals_and_fast_second_start(self):
        source = self.source('MaterialPlanner', 'frame.png')
        source.write_bytes(b'permanent')
        result = storage.migrate(self.repo, self.target)
        self.assertEqual((self.target / 'MaterialPlanner/frame.png').read_bytes(), source.read_bytes())
        self.assertEqual(result['paths']['logs'], str(self.repo / 'logs'))
        with patch.object(storage, 'discover', side_effect=AssertionError('must not rescan')):
            self.assertEqual(storage.migrate(self.repo, self.target), result)

    def test_wal_committed_rows_preserved(self):
        path = self.source('MaterialPlanner', 'index.sqlite3')
        writer = sqlite3.connect(path)
        self.addCleanup(writer.close)
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('CREATE TABLE claims(id TEXT PRIMARY KEY, quantity INTEGER)')
        writer.execute("INSERT INTO claims VALUES ('claim', 42)")
        writer.commit()
        storage.migrate(self.repo, self.target)
        with closing(sqlite3.connect(self.target / 'MaterialPlanner/index.sqlite3')) as copied:
            self.assertEqual(copied.execute('SELECT * FROM claims').fetchall(), [('claim', 42)])
            self.assertEqual(copied.execute('PRAGMA integrity_check').fetchone(), ('ok',))

    def test_interruption_resumes_and_never_commits_early(self):
        self.source('MaterialPlanner', 'first').write_bytes(b'one')
        self.source('MaterialPlanner', 'second').write_bytes(b'two')
        def stop(message):
            if message.startswith('已校验'): raise InterruptedError('stop')
        with self.assertRaises(InterruptedError): storage.migrate(self.repo, self.target, progress=stop)
        self.assertFalse((self.repo / 'configs/runtime_storage.json').exists())
        storage.migrate(self.repo, self.target)
        self.assertEqual((self.target / 'MaterialPlanner/second').read_bytes(), b'two')

    def test_nas_reference_rebound(self):
        marker = self.source('CompletionEvidence', 'pending_verified/event/nas.json')
        marker.parent.mkdir(parents=True)
        old = self.source('diagnostics', 'states/run--batch.json')
        marker.write_text(json.dumps({'state': str(old)}))
        storage.migrate(self.repo, self.target)
        copied = storage.read_json(self.target / 'CompletionEvidence/pending_verified/event/nas.json')
        self.assertEqual(copied['state'], str(self.target / 'diagnostics/states/run--batch.json'))

    def test_target_not_owned_is_rejected(self):
        self.target.mkdir()
        (self.target / 'keep').write_bytes(b'other instance')
        with self.assertRaises(ValueError): storage.migrate(self.repo, self.target)
        self.assertEqual((self.target / 'keep').read_bytes(), b'other instance')

    def test_low_space_never_switches(self):
        with patch.object(storage.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 1})()):
            with self.assertRaises(OSError): storage.migrate(self.repo, self.target)
        self.assertFalse((self.repo / 'configs/runtime_storage.json').exists())

    def test_changed_source_during_copy_rejected(self):
        source = self.source('MaterialPlanner', 'frame')
        source.write_bytes(b'one')
        def change(message):
            if message.startswith('已校验'): source.write_bytes(b'modified')
        with self.assertRaises(OSError): storage.migrate(self.repo, self.target, progress=change)
        self.assertFalse((self.repo / 'configs/runtime_storage.json').exists())

    def test_hard_process_exit_resumes_from_uncheckpointed_copy(self):
        self.source('MaterialPlanner', 'frame').write_bytes(b'preserved')
        code = '''import sys,json,os
from src.runtime import storage_bootstrap as s
s.discover=lambda repo:json.loads(sys.argv[3])
def progress(message):
    if message.startswith('已校验'): os._exit(17)
s.migrate(sys.argv[1],sys.argv[2],progress=progress)
'''
        result = subprocess.run([sys.executable, '-c', code, str(self.repo), str(self.target),
                                 json.dumps(self.sources)], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertFalse((self.repo / 'configs/runtime_storage.json').exists())
        storage.migrate(self.repo, self.target)
        self.assertEqual((self.target / 'MaterialPlanner/frame').read_bytes(), b'preserved')

    def test_committed_root_missing_marker_is_not_an_empty_install(self):
        storage.migrate(self.repo, self.target)
        (self.target / 'migration.json').unlink()
        with self.assertRaises(OSError): storage.bootstrap(self.repo)

    def test_bootstrap_import_does_not_initialize_framework(self):
        code = "import sys; import src.runtime.storage_bootstrap; assert 'ok' not in sys.modules; assert 'config' not in sys.modules"
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_repositories_keep_images_and_statistics(self):
        import cv2
        import numpy as np
        from uuid import uuid4
        from src.materials.repository import MaterialRepository
        from src.evidence.repository import EvidenceRepository
        material = MaterialRepository(self.sources['MaterialPlanner']['source'])
        record = str(uuid4())
        _, data = cv2.imencode('.png', np.zeros((12, 20, 3), np.uint8))
        material.save_frame(record, 0, data.tobytes())
        evidence = EvidenceRepository(self.sources['CompletionEvidence']['source'])
        saved = evidence.save(dict(profile_id=str(uuid4()), project_id='daily_activity'),
                              np.zeros((12, 20, 3), np.uint8))
        storage.migrate(self.repo, self.target)
        self.assertEqual((self.target / f'MaterialPlanner/assets/{record}/0000.png').read_bytes(), data.tobytes())
        self.assertTrue((self.target / 'CompletionEvidence' / saved['image_path']).is_file())
        self.assertEqual(storage.read_json(self.target / 'migration/asset-check.json')['existing_anomalies'], [])


if __name__ == '__main__': unittest.main()
