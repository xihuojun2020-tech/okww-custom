import copy
import tempfile
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication
from src.gui.ForgeryQuotaWidget import ForgeryQuotaWidget
from src.task.forgery_quota_plan import FORGERY_GOALS
from tests.TestForgeryQuotaPlan import goal
from tests.fixture_support import make_account_environment
from src.account_repository import ProfileEditScope


class TestForgeryQuotaUI(unittest.TestCase):
    def test_inventory_rebase_keeps_history_and_demand_edits_keep_round(self):
        from src.task.forgery_quota_progress import ForgeryQuotaProgress
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            identity = env.repository.list_profiles()[0].profile_id
            row = dict(goal(1, 150), inventory=dict(gold=0, purple=0, blue=0, green=25))
            progress = ForgeryQuotaProgress(env.integrity, identity)
            event = progress.begin(row['goal_id'], 1, 80, 'original')
            progress.resolve(event, 80)
            widget = ForgeryQuotaWidget({FORGERY_GOALS: [row]}, env.integrity, identity)
            try:
                self.assertIn('尚缺 75', widget.rows[0]['status'].text())
                widget.rows[0]['fields']['green'].setText('200')
                self.assertEqual(row['goal_id'], widget.values()[0]['goal_id'])
                widget.rows[0]['inventory_fields']['green'].setText('75')
                widget._inventory_changed(0)
                with self.assertRaises(ValueError):
                    widget.values()
                widget._new_round(0)
                updated = widget.values()[0]
                self.assertNotEqual(row['goal_id'], updated['goal_id'])
                self.assertEqual(75, updated['inventory']['green'])
                self.assertIn('已确认新增 0', widget.rows[0]['status'].text())
                self.assertEqual(50, progress.earned()[row['goal_id']])
                widget.mode.setCurrentIndex(widget.mode.findData('unlimited'))
                self.assertEqual(updated, widget.values()[0])
            finally:
                widget.timer.stop()
                widget.deleteLater()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_stable_roundtrip_new_round_and_domain_reset(self):
        rows = [goal(1, 50), goal(3, 25)]
        widget = ForgeryQuotaWidget({FORGERY_GOALS: rows})
        try:
            self.assertEqual(rows, widget.values())
            widget.refresh()
            self.assertEqual(rows, widget.values())
            widget.rows[0]['fields']['gold'].setText('1')
            self.assertEqual(rows[0]['goal_id'], widget.values()[0]['goal_id'])
            widget._new_round(0)
            new = widget.values()[0]['goal_id']
            self.assertNotEqual(rows[0]['goal_id'], new)
            widget.rows[0]['target'].setCurrentIndex(widget.rows[0]['target'].findData(2))
            self.assertNotEqual(new, widget.values()[0]['goal_id'])
        finally:
            widget.deleteLater()

    def test_template_new_account_fresh_ids_and_old_settings_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(Path(root))
            original = env.repository.load_profile(env.repository.list_profiles()[0].profile_id)
            tasks = copy.deepcopy(dict(original.tasks))
            tasks[FORGERY_GOALS] = [goal()]
            saved = env.repository.publish_profile(ProfileEditScope(original.profile_id, original.revision),
                                                   {'account': original.account, 'tasks': tasks})
            for key, value in original.tasks.items():
                if key != FORGERY_GOALS:
                    self.assertEqual(value, saved.tasks[key])
            template = env.repository.load_profile_template(saved.profile_id)
            created = env.repository.create_profile({'display_name': 'NEW'}, template.tasks,
                                                     expected_revision=template.revision)
            self.assertNotEqual(tasks[FORGERY_GOALS][0]['goal_id'], created.tasks[FORGERY_GOALS][0]['goal_id'])
            self.assertEqual(tasks[FORGERY_GOALS][0]['need'], created.tasks[FORGERY_GOALS][0]['need'])

    def test_completed_boss_plan_closes_with_compare_and_preserves_other_fields(self):
        from src.task.DailyTask import DailyTask
        from src.task.world_boss_material_plan import MATERIAL_TARGETS, material_plan
        from src.task.world_boss_material_progress import WorldBossMaterialProgress
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(Path(root))
            record = env.repository.load_profile(env.repository.list_profiles()[0].profile_id)
            tasks = dict(record.tasks)
            tasks[MATERIAL_TARGETS] = [{'boss': 'world_crownless', 'limit': 1},
                                       {'boss': 'none', 'limit': 0}, {'boss': 'none', 'limit': 0}]
            saved = env.repository.publish_profile(ProfileEditScope(record.profile_id, record.revision),
                                                   {'account': record.account, 'tasks': tasks})
            progress = WorldBossMaterialProgress(env.integrity, record.profile_id)
            event = progress.begin('world_crownless', 60, 'rev')
            progress.resolve(event, True)
            task = Mock(spec=DailyTask)
            task.integrity_service = env.integrity
            task._active_profile_id.return_value = record.profile_id
            self.assertTrue(DailyTask._close_completed_material_plan(task, material_plan(saved.tasks)))
            updated = env.repository.load_profile(record.profile_id)
            self.assertTrue(all(row['limit'] == 0 for row in material_plan(updated.tasks)))
            self.assertEqual(tasks['Which to Farm'], updated.tasks['Which to Farm'])
            self.assertEqual({'world_crownless': 1}, progress.counts())
            self.assertFalse(DailyTask._close_completed_material_plan(task, material_plan(saved.tasks)))
