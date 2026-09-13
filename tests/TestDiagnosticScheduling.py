import unittest
import tempfile
import json
from pathlib import Path
from src.runtime.diagnostic_uploader import batch_timeout, fair_batches


class TestDiagnosticScheduling(unittest.TestCase):
    def test_large_batch_gets_complete_budget(self):
        self.assertGreater(batch_timeout({'files': [{'size': 26 * 1024**2 // 12}] * 12}), 120)
        self.assertEqual(batch_timeout({'files': [{'size': 0}]}), 45)
        self.assertEqual(batch_timeout({'files': [{'size': 256 * 1024**2}]}), 180)

    def test_fairness_survives_round_restart(self):
        pending = [(0, i, Path(f'error{i}'), 120) for i in range(10)]
        pending += [(1, 20+i, Path(f'small{i}'), 45) for i in range(10)]
        pending += [(2, -1, Path('old-large'), 180)]
        groups, slot = [], 0
        for _ in range(5):
            row, slot = next(fair_batches(pending, slot))
            groups.append(row[0])
            pending.remove(row)
        self.assertEqual(groups, [0, 0, 1, 1, 2])

    def test_empty_priority_lanes_do_not_block_other_batches(self):
        pending = [(2, i, Path(str(i)), 90) for i in range(10)]
        self.assertEqual(len(list(fair_batches(pending))), 10)

    def test_bounded_queue_scan_rotates_and_legacy_empty_pointers_work(self):
        from src.runtime.diagnostic_queue import queue_batch, pending_batches
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for i in range(8):
                batch = root / 'run' / 'batches' / str(i)
                batch.mkdir(parents=True)
                (batch / '_READY').touch()
                queue_batch(batch)
            (root / 'pending-index.json').write_text(json.dumps({'reconciled_at': 1000}))
            first = list(pending_batches(root, now=1001, limit=4))
            second = list(pending_batches(root, now=1001, limit=4))
            self.assertEqual(len(set(first + second)), 8)
            self.assertEqual(len(list(pending_batches(root, now=1001))), 8)
