"""Offline regression checks for confirmed runtime review findings."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.runtime.storage_bootstrap import SCHEMA
from src.runtime.storage_handoff import quiesce_uploaders


class TestStorageHandoff(unittest.TestCase):
    def test_successful_current_schema_commit_keeps_old_actions_disabled(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder) / 'repo'
            destination = Path(folder) / 'data'
            (repo / 'configs').mkdir(parents=True)
            with patch('src.runtime.storage_handoff.subprocess.run') as run, \
                    patch('psutil.process_iter', return_value=[]):
                run.return_value.returncode = 0
                with quiesce_uploaders(repo, destination):
                    (repo / 'configs/runtime_storage.json').write_text(
                        json.dumps({'root': str(destination), 'schema': SCHEMA}), encoding='utf-8')
            self.assertEqual([call.args[0][-1] for call in run.call_args_list], ['Pause'])

    def test_failed_migration_restores_old_actions_and_propagates_error(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder) / 'repo'
            destination = Path(folder) / 'data'
            repo.mkdir()
            with patch('src.runtime.storage_handoff.subprocess.run') as run, \
                    patch('psutil.process_iter', return_value=[]):
                run.return_value.returncode = 0
                with self.assertRaisesRegex(OSError, 'copy failed'):
                    with quiesce_uploaders(repo, destination):
                        raise OSError('copy failed')
            self.assertEqual([call.args[0][-1] for call in run.call_args_list], ['Pause', 'Restore'])


if __name__ == '__main__':
    unittest.main()
