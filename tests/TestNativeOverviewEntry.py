"""Real isolated overview uses shared leases and never initializes task owners."""

import unittest

from tests import TestAccountManagementEntry as management_fixture


class TestNativeOverviewEntry(unittest.TestCase):
    def test_real_readonly_window_stops_without_writing_data_or_loading_execution(self):
        self.verify_entry()

    def test_installed_payload_readonly_window_uses_core_without_checkout(self):
        from pathlib import Path
        import tempfile
        from scripts.build_native_gamepack import build_native_gamepack
        from gameframe.packages import install_archive
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installed = install_archive(build_native_gamepack(root / 'native.zip'), root / 'packages')
            self.verify_entry(source_root=installed.root / 'payload',
                              core_root=Path(__file__).resolve().parents[1])

    def verify_entry(self, **paths):
        probe = management_fixture.TestAccountManagementEntry()
        output = probe.run_probe('''
            import importlib.abc
            from unittest.mock import patch
            from src.management import AccountManagementService
            service = AccountManagementService(root / 'data', 'overview-test')
            source, preview = service.preview_first_account(display_name='A1', phone='19910000001',
                nickname='只读合成账号', sequence_ids=('序列1',))
            service.create_first_account(source, preview, confirm=True)
            data = root / 'data'
            def snapshot():
                return {str(p.relative_to(data)): p.read_bytes() for p in data.rglob('*') if p.is_file()}
            before = snapshot()
            class RejectExecution(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == 'ok' or fullname.startswith('ok.') or fullname in {
                            'src.runtime.native_combat_host', 'src.runtime.native_configuration'}:
                        raise AssertionError('overview imported execution: ' + fullname)
            sys.meta_path.insert(0, RejectExecution())
            from gameframe.process_locks import data_lease
            from src.native_overview import overview
            import threading
            from src.account_repository import AccountRepository
            read_started, read_finished, allow_read = threading.Event(), threading.Event(), threading.Event()
            original_load = AccountRepository.load_profile
            def delayed_read(repository, identity):
                read_started.set()
                assert allow_read.wait(3)
                result = original_load(repository, identity)
                read_finished.set()
                return result
            def release_read():
                assert read_started.wait(3)
                allow_read.set()
            threading.Timer(.1, release_read).start()
            with data_lease(data), patch('src.runtime.account_runtime_bootstrap.initialize_account_runtime',
                    side_effect=AssertionError('overview initialized runtime')), \\
                    patch.object(AccountRepository, 'load_profile', delayed_read):
                assert overview(data, 'overview-test') == 0
            assert read_finished.is_set(), 'data lease ended before the read worker'
            assert snapshot() == before
            assert not (data / 'okww监控室/CompletionEvidence/index.sqlite3').exists()
            assert not any(name == 'ok' or name.startswith('ok.') for name in sys.modules)
        ''', stdin='{"command":"stop"}\n', **paths)
        self.assertIn('overview-ready', output)


if __name__ == '__main__':
    unittest.main()
