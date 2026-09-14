import unittest
from unittest.mock import Mock,patch
from src.runtime import navigation_status as status
from ok import TaskDisabledException

class TestSpecialistNavigationStatus(unittest.TestCase):
    def setUp(self):
        with status._lock:status._recent.clear()
    def test_rounds_are_not_reported_as_clicks_or_fake_deadline(self):
        with status.observe_operation(Mock(),'切号：选择目标账号',max_attempts=5,attempt_label='选择轮次') as update:
            update('核对账号选择',2)
        row=status.snapshot()[-1]
        self.assertEqual(row['attempts'],2);self.assertIsNone(row['remaining'])
        self.assertEqual(row['status'],'已到达目标')
        self.assertIn('选择轮次 2/5',status.status_text())
    def test_failure_keeps_type_without_account_contents(self):
        with self.assertRaises(ValueError):
            with status.observe_operation(Mock(),'切号',max_attempts=5):
                raise ValueError('secret-account-name')
        self.assertEqual(status.snapshot()[-1]['error'],'ValueError')
        self.assertNotIn('secret-account-name',str(status.snapshot()))
    def test_failed_publishing_does_not_change_task_result_or_cancellation(self):
        with patch.object(status,'publish',side_effect=OSError('disk')):
            with status.observe_operation(Mock(),'深塔',max_attempts=3) as update:update('等待',1)
            with self.assertRaises(TaskDisabledException):
                with status.observe_operation(Mock(),'深塔',max_attempts=3):raise TaskDisabledException()

if __name__=='__main__':unittest.main()
