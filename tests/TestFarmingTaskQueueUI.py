import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PySide6.QtWidgets import QApplication, QLabel
from src.gui.FarmingTaskQueueWidget import FarmingTaskQueueWidget, FarmingTaskDialog
from src.task.farming_task_queue import FARMING_TASKS, new_task
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

    def test_forgery_one_goal_inventory_deficit_and_target_locked_on_edit(self):
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
        self.assertFalse(editor.target.isEnabled())
        self.assertEqual(editor.values()['id'], item['id'])

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
