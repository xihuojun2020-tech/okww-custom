import unittest
from unittest.mock import Mock, patch

from src.task.AutoAbyssTask import AutoAbyssTask


class TestFeatureVerificationNavigation(unittest.TestCase):
    def test_abyss_verifies_current_screen_and_preserves_failed_verification(self):
        for status in ('verified', 'unreadable', 'mismatch'):
            with self.subTest(status=status):
                task = Mock(spec=AutoAbyssTask)
                task.config = {}
                task.ocr.return_value = []
                task._scan_all_towers.return_value = {}
                task._run_towers.return_value = {}
                verification = Mock()
                verification.record.account = {}
                verification.finish.side_effect = lambda: (
                    task.ensure_main.assert_not_called() or status)
                journal = Mock()
                with patch('src.task.WWOneTimeTask.WWOneTimeTask.run'), \
                        patch('src.task.account_feature_verification.current_feature_run',
                              return_value=verification) as current, \
                        patch('src.task.abyss_cycle_progress.AbyssCycleProgress', return_value=journal):
                    if status == 'verified':
                        AutoAbyssTask.run(task)
                    else:
                        with self.assertRaisesRegex(RuntimeError, '结束特征码核验未通过'):
                            AutoAbyssTask.run(task)
                current.assert_called_once_with(task)
                verification.finish.assert_called_once()
                task.ensure_main.assert_not_called()
                task.openF2Book.assert_called_once()
                journal.verify_run.assert_called_once_with(status == 'verified')


if __name__ == '__main__':
    unittest.main()
