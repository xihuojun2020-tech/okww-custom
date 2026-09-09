import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from src.runtime.diagnostic_collector import FileCollector
from src.runtime.diagnostic_policy import DEFAULT_TARGET, POLICY, settings
from src.runtime.diagnostic_session import DiagnosticSession
from src.runtime.diagnostic_uploader import retry_pending, upload_one, validate_remote
from src.runtime.diagnostic_retention import weekly_cleanup, purge_remote_logs, WEEK


class TestDiagnosticPolicy(unittest.TestCase):
    def test_default_nas_uses_current_smb_host(self):
        self.assertEqual(r'\\192.168.3.161\xihuojun 共享给我\AI诊断', DEFAULT_TARGET)

    @unittest.skipUnless(os.name == 'nt', 'Windows isolated uploader runtime')
    def test_independent_runtime_preserves_source_identity_and_ignores_pythonpath(self):
        from src.runtime.diagnostic_runtime import prepare_runtime, check_runtime, isolated_environment
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir='E:/OKWW-Test' if Path('E:/OKWW-Test').is_dir() else None,
                                         prefix='runtime-probe-') as directory:
            with patch.dict(os.environ, {'PYTHONPATH': str(source), 'PYAPPIFY_PID': '123'}):
                bundle = prepare_runtime(source, home=directory)
                check_runtime(bundle)
                self.assertNotIn('PYTHONPATH', isolated_environment())
                self.assertNotIn('PYAPPIFY_PID', isolated_environment())
            command = [str(bundle / 'python/python.exe'), '-E', '-s', '-c',
                       'from src.runtime.diagnostic_policy import REPO, installation_id; print(str(REPO)); print(installation_id())']
            result = subprocess.run(command, cwd=bundle, capture_output=True, text=True, check=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            from src.runtime.diagnostic_policy import installation_id
            self.assertEqual(result.stdout.splitlines(), [str(source), installation_id(source)])
            self.assertEqual(prepare_runtime(source, home=directory), bundle)
            self.assertFalse(bundle.is_relative_to(source))
            self.assertTrue((bundle / 'python/Lib/site-packages/win32timezone.py').is_file())
            self.session.record_event('isolated-worker-probe', {})
            self.session.finish(timeout=5)
            batch = next(self.session.run.glob('batches/*/_READY')).parent
            result = subprocess.run([str(bundle / 'python/python.exe'), '-E', '-s', '-m',
                                     'src.runtime.diagnostic_uploader', '--upload-one', str(batch),
                                     '--target', str(self.remote)], cwd=bundle,
                                    capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(list(self.remote.rglob('_UPLOAD_COMPLETE')))

    def test_background_runtime_cannot_be_installed_inside_application(self):
        from src.runtime.diagnostic_runtime import prepare_runtime
        source = Path(__file__).resolve().parents[1]
        with self.assertRaises(ValueError):
            prepare_runtime(source, home=source / 'forbidden-background')

    def test_repaired_runtime_retries_only_incomplete_bundle_failures(self):
        from src.runtime.diagnostic_lifecycle import reset_incomplete_runtime_retries
        states = self.root / 'states'
        states.mkdir(parents=True)
        incomplete = states / 'incomplete.json'
        network = states / 'network.json'
        incomplete.write_text(json.dumps({'status': 'retrying', 'next_retry': 99,
                                          'last_error': "No module named 'win32timezone'"}))
        network.write_text(json.dumps({'status': 'retrying', 'next_retry': 99,
                                       'last_error': 'NAS authentication failed'}))
        reset_incomplete_runtime_retries(self.root)
        self.assertEqual(json.loads(incomplete.read_text())['next_retry'], 0)
        self.assertEqual(json.loads(network.read_text())['next_retry'], 99)

    @unittest.skipUnless(os.name == 'nt', 'Windows scheduled task migration')
    def test_task_migration_rolls_back_on_failure_and_switches_on_success(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/migrate_diagnostic_task.ps1'
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        for fail in (True, False):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                bundle = root / 'bundle'
                (bundle / 'src/runtime').mkdir(parents=True)
                (bundle / 'ready.json').write_text(json.dumps({'source_repo': str(root)}))
                (bundle / 'src/runtime/install_diagnostic_task.ps1').write_text(
                    "throw 'synthetic install failure'" if fail else
                    "$global:action = Join-Path $global:bundlePath 'python/pythonw.exe'", encoding='utf-8')
                wrapper = root / 'probe.ps1'
                wrapper.write_text('''
$ErrorActionPreference = 'Stop'
$global:restored = $false
$global:action = 'old-python.exe'
$global:bundlePath = BUNDLE
function Get-ScheduledTask { [pscustomobject]@{Description=DESCRIPTION;Actions=[pscustomobject]@{Execute=$global:action}} }
function Export-ScheduledTask { '<original-task />' }
function Disable-ScheduledTask { }
function Enable-ScheduledTask { }
function Stop-ScheduledTask { }
function Get-CimInstance { }
function Register-ScheduledTask { param($TaskName,$Xml,[switch]$Force); if ($Xml -ne '<original-task />') { throw 'bad rollback' }; $global:restored=$true }
$failed = $false
try { & SCRIPT -SourceRepo SOURCE -Root SPOOL -Bundle BUNDLE -TaskName 'fake-owned-task' | Out-Null }
catch { $failed=$true }
@{failed=$failed; restored=$global:restored; action=$global:action} | ConvertTo-Json
'''.replace('DESCRIPTION', quote('okww diagnostics uploader owned by ' + str(root)))
                    .replace('SCRIPT', quote(script)).replace('SOURCE', quote(root))
                    .replace('SPOOL', quote(root / 'spool')).replace('BUNDLE', quote(bundle)), encoding='utf-8-sig')
                result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(wrapper)],
                                        capture_output=True, text=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                state = json.loads(result.stdout)
                self.assertEqual(state['failed'], fail)
                self.assertEqual(state['restored'], fail)
                self.assertTrue(list((bundle / 'migration').glob('*.xml')))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        temporary_root = Path(self.temp.name).resolve()
        self.root = temporary_root / 'spool'
        self.remote = temporary_root / 'nas'
        self.session = DiagnosticSession(self.root, '1.37.00')

    def tearDown(self):
        self.session.finish(timeout=5)
        self.temp.cleanup()

    def test_policy_is_mandatory_and_preserves_start_boundary(self):
        first = settings(self.root)
        value = dict(first, enabled=False)
        (self.root / 'settings.json').write_text(json.dumps(value))
        second = settings(self.root)
        self.assertTrue(second['enabled'])
        self.assertEqual(first['started_at'], second['started_at'])
        self.assertEqual(first['device_id'], second['device_id'])

    def test_legacy_official_nas_targets_migrate_without_resetting_identity(self):
        for target in (r'\\192.168.3.170\xihuojun 共享给我\AI诊断',
                       r'\\192.168.3.170\AI诊断'):
            with self.subTest(target=target):
                value = {'policy': POLICY, 'started_at': 123.0, 'device_id': 'device',
                         'target': target, 'enabled': True}
                (self.root / 'settings.json').parent.mkdir(parents=True, exist_ok=True)
                (self.root / 'settings.json').write_text(json.dumps(value), encoding='utf-8')
                migrated = settings(self.root)
                self.assertEqual(migrated['target'], DEFAULT_TARGET)
                self.assertEqual(migrated['started_at'], 123.0)
                self.assertEqual(migrated['device_id'], 'device')

    def test_custom_nas_target_is_not_migrated(self):
        target = r'\\nas.lan\custom\diagnostics'
        value = {'policy': POLICY, 'started_at': 123.0, 'device_id': 'device',
                 'target': target, 'enabled': True}
        (self.root / 'settings.json').parent.mkdir(parents=True, exist_ok=True)
        (self.root / 'settings.json').write_text(json.dumps(value), encoding='utf-8')
        self.assertEqual(settings(self.root)['target'], target)

    @unittest.skipUnless(os.name == 'nt', 'Windows scheduled task')
    def test_scheduler_revision_migrates_cached_console_task(self):
        from src.runtime.diagnostic_policy import ensure_task, SCHEDULER_REVISION
        state = self.root / 'scheduler.json'
        state.write_text(json.dumps({'status': 'installed', 'root': str(self.root),
                                    'checked_at': time.time(), 'revision': SCHEDULER_REVISION - 1}))
        with patch('src.runtime.diagnostic_policy.subprocess.run', return_value=SimpleNamespace(returncode=0)) as run:
            ensure_task(self.root)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)
            ensure_task(self.root)
            self.assertEqual(run.call_count, 1)
        self.assertEqual(json.loads(state.read_text())['revision'], SCHEDULER_REVISION)

    @unittest.skipUnless(os.name == 'nt', 'Windows scheduled task')
    def test_scheduler_cache_must_match_current_runtime_bundle(self):
        from src.runtime.diagnostic_policy import ensure_task, SCHEDULER_REVISION
        state = self.root / 'scheduler.json'
        state.write_text(json.dumps({
            'status': 'installed', 'root': str(self.root), 'checked_at': time.time(),
            'revision': SCHEDULER_REVISION, 'runtime': r'E:\OKWW-Background\old\python\pythonw.exe',
            'working_directory': r'E:\OKWW-Background\old',
        }))
        with patch('src.runtime.diagnostic_policy.subprocess.run',
                   return_value=SimpleNamespace(returncode=0)) as run:
            ensure_task(self.root)
            self.assertEqual(run.call_count, 1)
            ensure_task(self.root)
            self.assertEqual(run.call_count, 1)
        saved = json.loads(state.read_text())
        self.assertEqual(saved['runtime'], str(Path(sys.executable).resolve()))
        self.assertEqual(saved['working_directory'], str(Path(__file__).resolve().parents[1]))

    @unittest.skipUnless(os.name == 'nt', 'Windows scheduled task')
    def test_installer_selects_pythonw_without_registering_real_task(self):
        script = Path(__file__).resolve().parents[1] / 'src/runtime/install_diagnostic_task.ps1'
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        command = ('& ' + quote(script) + ' -Preview -TaskName okww-silent-action-preview'
                   + ' -PythonExe ' + quote(sys.executable) + ' -Root ' + quote(self.root))
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', command],
                                capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        action = json.loads(result.stdout.decode(errors='replace'))
        chosen = Path(action['Execute'])
        self.assertEqual(chosen.name.casefold(), 'pythonw.exe')
        self.assertEqual(chosen.parent, Path(sys.executable).parent)

    def test_old_manifest_is_never_backfilled(self):
        self.session.record_event('old', {})
        self.session.finish(timeout=5)
        for p in self.session.run.glob('batches/*/manifest.json'):
            manifest = json.loads(p.read_text(encoding='utf-8'))
            manifest.pop('policy')
            p.write_text(json.dumps(manifest))
        calls = []
        retry_pending(self.root, self.remote, transfer=lambda *args: calls.append(args))
        self.assertEqual(calls, [])

    def test_incremental_files_skip_history_and_include_new_images(self):
        from PIL import Image
        source = Path(self.temp.name) / 'app'
        logs, pictures = source / 'logs', source / 'screenshots'
        logs.mkdir(parents=True)
        pictures.mkdir()
        log = logs / 'app.log'
        log.write_text('HISTORICAL_MUST_NOT_UPLOAD\n', encoding='utf-8')
        Image.new('RGB', (5, 5), 'red').save(pictures / 'old.png')
        collector = FileCollector(source, self.root)
        with log.open('a', encoding='utf-8') as stream:
            stream.write('NEW_DATA\n')
        Image.new('RGB', (5, 5), 'blue').save(pictures / 'new.png')
        collector.collect(self.session.run)
        manifests = list(self.session.run.glob('batches/*/manifest.json'))
        all_data = b''
        images = 0
        for path in manifests:
            for item in json.loads(path.read_text(encoding='utf-8'))['files']:
                all_data += (path.parent / item['path']).read_bytes()
                images += item['path'].startswith('截图/')
        self.assertIn(b'NEW_DATA', all_data)
        self.assertNotIn(b'HISTORICAL_MUST_NOT_UPLOAD', all_data)
        self.assertEqual(images, 1)
        FileCollector(source, self.root).collect(self.session.run)
        self.assertEqual(len(list(self.session.run.glob('batches/*/manifest.json'))), len(manifests))

    def test_truncated_image_is_skipped_then_retried_after_repair(self):
        from PIL import Image
        source = Path(self.temp.name) / 'app'
        (source / 'logs').mkdir(parents=True)
        pictures = source / 'screenshots'
        pictures.mkdir()
        collector = FileCollector(source, self.root)
        log = source / 'logs' / 'app.log'
        log.write_text('still uploads\n', encoding='utf-8')
        broken = pictures / 'broken.png'
        broken.write_bytes(b'not-a-complete-png')
        collector.collect(self.session.run)
        warning = self.root / 'collector-error.json'
        self.assertTrue(warning.exists())
        self.assertFalse(list(self.session.run.glob('batches/*/截图/**/*.png')))
        self.assertTrue(list(self.session.run.glob('batches/*/日志/**/*.log')))
        Image.new('RGB', (5, 5), 'green').save(broken)
        collector.collect(self.session.run)
        self.assertFalse(warning.exists())
        self.assertTrue(list(self.session.run.glob('batches/*/截图/**/*.png')))

    def test_weekly_cleanup_retains_images_pending_and_unrelated_files(self):
        from PIL import Image
        self.session.record_event('new-log', {'text': 'diagnostic evidence'})
        source = Path(self.temp.name) / 'image.png'
        Image.new('RGB', (10, 10)).save(source)
        self.session.add_screenshot(source)
        self.session.finish(timeout=5)
        retry_pending(self.root, self.remote, transfer=lambda b, t, _: upload_one(b, t))
        unrelated = self.remote / 'unrelated.log'
        unrelated.write_text('KEEP')
        now = time.time() + WEEK + 1
        weekly_cleanup(self.root, self.remote, now=now,
                       purge=lambda b, t: purge_remote_logs(b, t, now=now))
        self.assertTrue(list(self.remote.rglob('*.png')))
        self.assertTrue(list((self.session.run / 'screenshots').glob('*.png')))
        self.assertEqual(unrelated.read_text(), 'KEEP')
        self.assertFalse((self.session.run / 'events.jsonl').exists())
        self.assertFalse(list(self.remote.rglob('_UPLOAD_COMPLETE')))
        self.assertTrue(list(self.remote.rglob('_LOGS_PURGED')))
        for marker in self.remote.rglob('_LOGS_PURGED'):
            retained = validate_remote(marker.parent)
            self.assertTrue(retained['logs_purged'])
            self.assertTrue(all(item['path'].startswith('截图/') for item in retained['files']))
        # A second pass in the same week performs no deletes/network access.
        weekly_cleanup(self.root, self.remote, now=now + 1,
                       purge=lambda *_: self.fail('ran twice in one week'))

    def test_cleanup_does_not_remove_unuploaded_or_young_logs(self):
        self.session.record_event('pending', {})
        self.session.finish(timeout=5)
        now = time.time() + WEEK + 1
        weekly_cleanup(self.root, self.remote, now=now,
                       purge=lambda *_: self.fail('unuploaded batch was deleted'))
        self.assertTrue((self.session.run / 'events.jsonl').exists())
        retry_pending(self.root, self.remote, transfer=lambda b, t, _: upload_one(b, t))
        for batch in self.session.run.glob('batches/*'):
            with self.assertRaises(ValueError):
                purge_remote_logs(batch, self.remote)

    def test_original_collected_log_is_removed_only_after_delivery(self):
        source = Path(self.temp.name) / 'app'
        (source / 'logs').mkdir(parents=True)
        collector = FileCollector(source, self.root)
        log = source / 'logs' / 'new.log'
        log.write_text('NEW\n')
        collector.collect(self.session.run)
        self.session.finish(timeout=5)
        retry_pending(self.root, self.remote, transfer=lambda b, t, _: upload_one(b, t))
        now = time.time() + WEEK + 1
        weekly_cleanup(self.root, self.remote, now=now, source_root=source,
                       purge=lambda b, t: purge_remote_logs(b, t, now=now))
        self.assertFalse(log.exists())

    def test_after_exit_collector_captures_late_file_and_does_not_repeat(self):
        from src.runtime.diagnostic_collector import collect_after_exit
        source = Path(self.temp.name) / 'app'
        (source / 'logs').mkdir(parents=True)
        (source / 'config.py').write_text('version = "1.37.00"\n')
        FileCollector(source, self.root)
        (source / 'logs' / 'late.log').write_text('LATE_EVENT\n')
        collect_after_exit(self.root, source)
        runs = [p for p in self.root.iterdir() if (p / 'metadata.json').exists()]
        self.assertEqual(len(runs), 2)
        collect_after_exit(self.root, source)
        self.assertEqual(len([p for p in self.root.iterdir() if (p / 'metadata.json').exists()]), 2)

    def test_rewritten_log_does_not_lose_new_prefix(self):
        source = Path(self.temp.name) / 'app'
        (source / 'logs').mkdir(parents=True)
        log = source / 'logs' / 'app.log'
        log.write_text('HISTORICAL\n')
        collector = FileCollector(source, self.root)
        log.write_text('NEW_PREFIX and a longer replacement record\n')
        collector.collect(self.session.run)
        payload = b''.join(p.read_bytes() for p in self.session.run.glob('batches/*/日志/*/*/*/*/*.log'))
        self.assertIn(b'NEW_PREFIX', payload)
        self.assertNotIn(b'HISTORICAL', payload)

    def test_incomplete_json_does_not_block_other_files_or_repeat_forever(self):
        source = Path(self.temp.name) / 'app'
        (source / 'logs').mkdir(parents=True)
        collector = FileCollector(source, self.root)
        bad = source / 'logs' / 'a.json'
        bad.write_text('{incomplete')
        (source / 'logs' / 'b.log').write_text('HEALTHY_LOG\n')
        collector.collect(self.session.run)
        self.assertFalse(collector.changed('logs/a.json', bad))
        self.assertTrue(list(self.session.run.glob('batches/*/_READY')))
        self.assertFalse(list(self.session.run.glob('collected-*.json')))
        bad.write_text('{"complete": true}')
        collector.collect(self.session.run)
        self.assertTrue(list(self.session.run.glob('collected-*.json')))

    def test_interrupted_retention_resumes_without_deleting_images(self):
        self.session.record_event('retention-fault', {})
        self.session.finish(timeout=5)
        batch = next(p for p in self.session.run.glob('batches/*')
                     if any(x['path'].endswith('.jsonl') for x in json.loads((p / 'manifest.json').read_text(encoding='utf-8'))['files']))
        upload_one(batch, self.remote)
        original = Path.unlink
        def fail(path, *args, **kwargs):
            if path.is_relative_to(self.remote) and path.suffix == '.jsonl':
                raise OSError('synthetic retention interruption')
            return original(path, *args, **kwargs)
        now = time.time() + WEEK + 1
        with patch.object(Path, 'unlink', fail):
            with self.assertRaises(OSError):
                purge_remote_logs(batch, self.remote, now=now)
        self.assertFalse(list(self.remote.rglob('_UPLOAD_COMPLETE')))
        self.assertTrue(list(self.remote.rglob('_PURGING_LOGS')))
        purge_remote_logs(batch, self.remote, now=now)
        self.assertTrue(list(self.remote.rglob('_LOGS_PURGED')))
        self.assertFalse(list(self.remote.rglob('_PURGING_LOGS')))


if __name__ == '__main__':
    unittest.main()
