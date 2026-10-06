import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
import tempfile
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QLabel
from src.gui.FarmingTaskQueueWidget import FarmingTaskQueueWidget, FarmingTaskDialog
from src.task.farming_task_queue import FARMING_TASKS, new_task, task_progress, task_status, require_resolved_claims
from src.task.weekly_boss import WEEKLY_BOSSES


class TestFarmingTaskQueueUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_group_order_and_pause_round_trip(self):
        a = new_task('weekly', dict(boss=WEEKLY_BOSSES[0].key, limit=3), '甲')
        b = new_task('weekly', dict(boss=WEEKLY_BOSSES[0].key, limit=4), '乙')
        widget = FarmingTaskQueueWidget({FARMING_TASKS: [a, b]})
        self.addCleanup(widget.close)
        widget.move(1, -1)
        widget.toggle(0)
        saved = widget.values()
        restored = FarmingTaskQueueWidget({FARMING_TASKS: saved})
        self.addCleanup(restored.close)
        self.assertEqual(restored.values(), saved)
        self.assertEqual(saved[0]['id'], b['id'])
        self.assertFalse(saved[0]['enabled'])

    def test_legacy_unlimited_forgery_and_tacet_save_without_hidden_validation(self):
        widget = FarmingTaskQueueWidget({'Which to Farm': 'Forgery Challenge',
            'Which Forgery Challenge to Farm': 7, 'Weekly Boss Target': '无'})
        self.addCleanup(widget.close)
        self.assertEqual(widget.values()[0]['params'], dict(mode='unlimited', domain=7))
        dialog = FarmingTaskDialog()
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.values()['kind'], 'tacet')
        self.assertEqual(dialog.values()['params']['target'], dialog.target.currentData())

    def test_forgery_one_goal_inventory_deficit_and_target_edit_starts_new_progress(self):
        dialog = FarmingTaskDialog()
        self.addCleanup(dialog.close)
        dialog.kind.setCurrentIndex(dialog.kind.findData('forgery'))
        quota = dialog.quota
        quota.mode.setCurrentIndex(quota.mode.findData('materials'))
        self.assertEqual(len(quota.rows), 1)
        row = quota.rows[0]
        row['inventory_fields']['blue'].setText('2')
        row['fields']['purple'].setText('2')
        item = dialog.values()
        from src.task.forgery_quota_plan import goal_units
        self.assertEqual(goal_units(item['params']['goal']), 12)
        editor = FarmingTaskDialog(item)
        self.addCleanup(editor.close)
        self.assertTrue(editor.target.isEnabled())
        self.assertEqual(editor.values()['id'], item['id'])
        editor.target.setCurrentIndex((editor.target.currentIndex() + 1) % editor.target.count())
        edited = editor.values()
        self.assertNotEqual(edited['params']['goal']['goal_id'], item['params']['goal']['goal_id'])
        self.assertEqual(edited['params']['domain'], edited['params']['goal']['domain'])
        self.assertEqual(goal_units(edited['params']['goal']), 12)

    def test_all_existing_task_types_allow_target_changes_and_keep_task_settings(self):
        from src.task.world_boss_materials import TARGETS_BY_ID
        cases = [('weekly', dict(boss=WEEKLY_BOSSES[0].key, limit=3)),
                 ('world_boss', dict(boss=next(iter(TARGETS_BY_ID)), limit=2)),
                 ('forgery', dict(mode='unlimited', domain=1)),
                 ('tacet', dict(target=1)), ('simulation', dict(target='Shell Credit'))]
        for kind, params in cases:
            with self.subTest(kind=kind):
                item = new_task(kind, params, '我的任务')
                item['enabled'] = False
                dialog = FarmingTaskDialog(item)
                self.addCleanup(dialog.close)
                self.assertTrue(dialog.target.isEnabled())
                self.assertEqual(dialog.values(), item)
                dialog.target.setCurrentIndex((dialog.target.currentIndex() + 1) % dialog.target.count())
                changed = dialog.values()
                self.assertNotEqual(changed['params'], item['params'])
                self.assertEqual(changed['name'], item['name'])
                self.assertFalse(changed['enabled'])
                self.assertEqual(changed['kind'], kind)
                self.assertNotEqual(changed['id'], item['id'])
                self.assertEqual(dialog.values()['id'], changed['id'])

    def test_weekly_auto_edit_isolates_old_counts_and_keeps_pending_journal(self):
        from src.config_integrity import ConfigIntegrityService
        from src.task.weekly_boss import WEEKLY_AUTO
        with tempfile.TemporaryDirectory() as temp:
            service = ConfigIntegrityService(temp)
            item = new_task('weekly', dict(boss=WEEKLY_BOSSES[0].key, limit=3))
            item['legacy_progress'] = True
            journal = task_progress(item, service, 'test-account')
            journal.correct(item['params']['boss'], 2)
            pending = journal.begin(item['params']['boss'], 'week', 3, 'r')
            dialog = FarmingTaskDialog(item, service, 'test-account')
            self.addCleanup(dialog.close)
            dialog.limit.setText('4')
            unchanged = dialog.values()
            self.assertEqual(unchanged['id'], item['id'])
            self.assertIn('2 / 4', task_status(unchanged, service, 'test-account')[2])
            dialog.target.setCurrentIndex(dialog.target.findData(WEEKLY_BOSSES[1].key))
            edited = dialog.values()
            self.assertNotIn('legacy_progress', edited)
            self.assertIn('0 / 4', task_status(edited, service, 'test-account')[2])
            dialog.target.setCurrentIndex(dialog.target.findData(WEEKLY_AUTO))
            dialog.limit.setText('不限')
            self.assertIn('已领取 0 / 不限', task_status(dialog.values(), service, 'test-account')[2])
            self.assertEqual(journal.counts()[item['params']['boss']], 2)
            self.assertIn(pending, journal.pending())
            with self.assertRaisesRegex(RuntimeError, '待核验'):
                require_resolved_claims({FARMING_TASKS: [edited]}, service, 'test-account')

    def test_pending_forgery_change_rejection_keeps_both_target_controls_consistent(self):
        from src.config_integrity import ConfigIntegrityService
        from tests.TestFarmingTaskQueue import TestFarmingTaskQueue
        item = TestFarmingTaskQueue().quota()
        with tempfile.TemporaryDirectory() as temp:
            service = ConfigIntegrityService(temp)
            journal = task_progress(item, service, 'test-account')
            journal.begin(item['params']['goal']['goal_id'], 1, 40, 'r')
            dialog = FarmingTaskDialog(item, service, 'test-account')
            self.addCleanup(dialog.close)
            with patch('src.gui.ForgeryQuotaWidget.QMessageBox.warning'):
                dialog.target.setCurrentIndex(dialog.target.findData(2))
            self.assertEqual(dialog.target.currentData(), 1)
            self.assertEqual(dialog.quota.rows[0]['target'].currentData(), 1)
            self.assertEqual(dialog.values(), item)

    def test_template_uses_one_queue_and_preserves_legacy_fields(self):
        from src.gui.AccountConfigTab import AccountTemplateDialog
        config = {'Which to Farm': 'Tacet Suppression', 'Which Tacet Suppression to Farm': 2,
                  'Weekly Boss Target': '无', 'Garden Execution Mode': 'closed'}
        dialog = AccountTemplateDialog(config)
        self.addCleanup(dialog.close)
        result = dialog.tasks()
        self.assertIn(FARMING_TASKS, dialog._widgets)
        self.assertNotIn('Which to Farm', dialog._widgets)
        self.assertEqual(result['Which Tacet Suppression to Farm'], 2)
        self.assertEqual(result[FARMING_TASKS][0]['params']['target'], 2)


if __name__ == '__main__':
    unittest.main()
