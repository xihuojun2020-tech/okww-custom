"""Native output relocation through the real storage transaction, temporary data only."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from src.runtime import storage_bootstrap as storage
from src.runtime.native_storage import NativeStorageService, NativeStorageCommittedError


class TestNativeStorage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.data = self.base / 'data'; self.data.mkdir()
        self.target = self.base / 'outputs'
        self.service = NativeStorageService(self.data)

    def test_native_sources_wal_originals_and_data_authority(self):
        paths = self.service.paths()
        self.assertEqual(paths['diagnostics'], self.data / 'okww监控室/diagnostics')
        self.assertEqual(paths['CompletionEvidence'], self.data / 'okww监控室/CompletionEvidence')
        for kind, name in (('diagnostics','report.txt'),('screenshots','shot.png'),('backups','backup.json')):
            paths[kind].mkdir(parents=True,exist_ok=True)
            (paths[kind]/name).write_bytes(kind.encode())
        configs = self.data/'configs'; configs.mkdir()
        (configs/'private-account.json').write_text('account remains')
        (self.data/'user_tasks').mkdir(); (self.data/'user_tasks/task.py').write_text('script remains')
        paths['CompletionEvidence'].mkdir(parents=True,exist_ok=True)
        (paths['screenshots']/'log').mkdir()
        (paths['screenshots']/'log/old.png').write_bytes(b'nested screenshot')
        (paths['recordings']/'recording.mp4').write_bytes(b'recording')
        (paths['runtime']/'workers').mkdir(parents=True)
        (paths['runtime']/'workers/current.json').write_text('control state')
        database = paths['CompletionEvidence']/'index.sqlite3'
        writer = sqlite3.connect(database); self.addCleanup(writer.close)
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('CREATE TABLE entries(value INTEGER)'); writer.execute('INSERT INTO entries VALUES (72)'); writer.commit()
        preview = self.service.preview(self.target)
        self.assertEqual(preview['scope'],'outputs')
        self.assertTrue(all(not item['history'] for item in preview['sources'].values()))
        with patch.object(storage,'discover',side_effect=AssertionError('must not discover legacy/global data')):
            result = self.service.migrate(preview)
        self.assertTrue(result['committed'])
        self.assertEqual((configs/'private-account.json').read_text(),'account remains')
        self.assertEqual((self.data/'user_tasks/task.py').read_text(),'script remains')
        selected = storage.read_json(configs/'runtime_storage.json')
        self.assertEqual(selected['root'],str(self.target))
        self.assertEqual(selected['paths']['logs'],str(self.data/'logs'))
        for kind, name in (('diagnostics','report.txt'),('screenshots','shot.png'),('backups','backup.json')):
            self.assertEqual((Path(selected['paths'][kind])/name).read_bytes(),kind.encode())
            self.assertTrue((paths[kind]/name).exists())
        with closing(sqlite3.connect(Path(selected['paths']['CompletionEvidence'])/'index.sqlite3')) as reader:
            self.assertEqual(reader.execute('SELECT value FROM entries').fetchall(),[(72,)])
            self.assertEqual(reader.execute('PRAGMA integrity_check').fetchone(),('ok',))
        self.assertEqual(self.service.paths()['screenshots'],self.target/'okww监控室/screenshots')
        self.assertEqual((self.target/'okww监控室/screenshots/log/old.png').read_bytes(),b'nested screenshot')
        self.assertEqual((self.target/'okww监控室/recordings/recording.mp4').read_bytes(),b'recording')
        self.assertFalse((self.target/'okww监控室/recordings/diagnostics').exists())
        self.assertFalse((self.target/'okww监控室/recordings/CompletionEvidence').exists())
        self.assertFalse((self.target/'okww监控室/recordings/log').exists())
        self.assertFalse((self.target/'okww监控室/recordings/shot.png').exists())
        self.assertFalse((self.target/'okww监控室/screenshots/CompletionEvidence').exists())
        self.assertFalse((self.target/'okww监控室/recordings/runtime').exists())
        self.assertEqual((paths['runtime']/'workers/current.json').read_text(),'control state')
        from src.runtime.native_screenshots import save_native_screenshot
        import numpy as np
        screenshot=save_native_screenshot(self.data,'new',np.ones((90,160,3),dtype=np.uint8))
        self.assertEqual(screenshot.parent,self.service.paths()['screenshots'])
        self.assertEqual(storage.read_json(self.target/'migration/progress.json')['phase'],'READY')
        self.assertTrue(database.exists())

    def test_active_owner_stale_preview_and_destination_rules(self):
        from gameframe.process_locks import data_lease, LeaseUnavailable
        preview = self.service.preview(self.target)
        with data_lease(self.data):
            with self.assertRaises(LeaseUnavailable): self.service.migrate(preview)
        self.assertFalse((self.data/'configs/runtime_storage.json').exists())
        for destination in (self.data,self.data/'inside',self.base):
            with self.assertRaises(ValueError): self.service.preview(destination)
        self.target.mkdir(); (self.target/'unowned').write_text('keep')
        with self.assertRaisesRegex(ValueError,'未归属'): self.service.preview(self.target)
        (self.target/'unowned').unlink()
        storage.atomic_json(self.data/'configs/runtime_storage.json',{'root':str(self.target),'paths':{}})
        with self.assertRaises(ValueError): self.service.migrate(preview)

    def test_failure_before_and_after_commit_is_explicit(self):
        preview = self.service.preview(self.target)
        with patch.object(storage,'copy_verified',side_effect=OSError('copy failed')):
            source=self.service.paths()['backups']; source.mkdir()
            (source/'a').write_bytes(b'a')
            with self.assertRaisesRegex(OSError,'copy failed'): self.service.migrate(preview)
        self.assertFalse((self.data/'configs/runtime_storage.json').exists())
        real_atomic = storage.atomic_json
        def failed_final_journal(path,value):
            if Path(path)==self.target/'migration/progress.json' and value.get('phase')=='READY':
                raise OSError('final journal failed')
            return real_atomic(path,value)
        preview=self.service.preview(self.target)
        with patch.object(storage,'atomic_json',side_effect=failed_final_journal):
            with self.assertRaises(NativeStorageCommittedError) as failed: self.service.migrate(preview)
        self.assertTrue(failed.exception.committed)
        self.assertEqual(storage.read_json(self.data/'configs/runtime_storage.json')['root'],str(self.target))

    def test_real_qt_tab_previews_and_uses_maintenance_coordination(self):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        output=TestAccountManagementEntry().run_probe('''
            import time
            from unittest.mock import patch
            from PySide6.QtWidgets import QApplication, QMessageBox
            from src.runtime.native_storage import NativeStorageService
            from src.gui.NativeStorageTab import NativeStorageTab
            app=QApplication([])
            data=root/'native-data'; data.mkdir()
            (data/'screenshots').mkdir()
            service=NativeStorageService(data)
            monitor=data/'okww监控室'; monitor.mkdir(); (monitor/'a.png').write_bytes(b'screenshot')
            calls=[]
            def maintain(work,success,failure,rebind):
                calls.append(rebind)
                try: result=work()
                except Exception as error: failure(error)
                else: success(result)
            tab=NativeStorageTab(service,maintain)
            tab.show()
            assert str(data)==tab.path_labels['data'].text()
            assert not tab.migrate_button.isEnabled()
            tab.destination.setText(str(root/'outputs'))
            tab.preview_button.click()
            deadline=time.monotonic()+10
            while tab.operation.busy:
                app.processEvents()
                if time.monotonic()>deadline: raise AssertionError('preview blocked')
                time.sleep(.005)
            assert tab.migrate_button.isEnabled(),tab.status.text()
            with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):
                tab.migrate_button.click()
            assert calls==[False] and '输出目录已提交' in tab.status.text(),tab.status.text()
            assert tab.path_labels['screenshots'].text()==str(root/'outputs/okww监控室/screenshots')
            assert (monitor/'a.png').exists() and (root/'outputs/okww监控室/screenshots/a.png').is_file()
            tab.close()
            print('native-storage-ui-pass')
        ''')
        self.assertIn('native-storage-ui-pass',output)

    def test_prepared_account_and_host_use_migrated_evidence_authority(self):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        output=TestAccountManagementEntry().run_probe('''
            import threading
            from src.management import AccountManagementService
            data=root/'native-data'
            service=AccountManagementService(data,'storage-test')
            source,preview=service.preview_first_account(display_name='A1',phone='19910000001',
                nickname='存储合成账号',sequence_ids=('序列1',))
            service.create_first_account(source,preview,confirm=True)
            from src.runtime.native_storage import NativeStorageService
            storage=NativeStorageService(data)
            storage.migrate(storage.preview(root/'outputs'))
            from src.runtime.account_runtime_bootstrap import prepare_native_account_runtime
            prepare_native_account_runtime(data,'storage-test')
            from src.evidence.service import get_evidence_service, close_existing_evidence_service
            evidence=get_evidence_service()
            assert evidence.repository.root==storage.paths()['CompletionEvidence']
            from gameframe.api import TaskContext
            from gameframe.devices.replay import ReplayDevice
            from src.runtime.native_combat_host import NativeCombatHost
            from src.combat.settings import COMBAT_GLOBAL_DEFAULTS,TEMPLATE_MATCHING_DEFAULTS
            host=NativeCombatHost(TaskContext(ReplayDevice([]),{},data,threading.Event(),'storage',lambda event:None),
                coco_path=Path(sys.argv[1])/'assets/coco_annotations.json',global_options=COMBAT_GLOBAL_DEFAULTS,
                ocr_engine=None,template_matching=TEMPLATE_MATCHING_DEFAULTS)
            assert host.executor.completion_evidence_service is evidence
            assert host.executor.completion_evidence_service.repository.root==root/'outputs/okww监控室/CompletionEvidence'
            close_existing_evidence_service()
            assert not host.context.device.actions
            print('native-evidence-authority-pass')
        ''')
        self.assertIn('native-evidence-authority-pass',output)
