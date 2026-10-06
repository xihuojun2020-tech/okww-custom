import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import QApplication
from src.account_config_editor import AccountConfigEditor
from src.account_task_state import AccountTaskCard
from src.gui.AccountConfigTab import AccountConfigTab
from src.gui.AccountTaskOverview import AccountTaskOverview
from src.gui.AccountSettingsTab import AccountSettingsTab
from src.gui.SequenceManagementTab import SequenceManagementTab
from src.sequence_repository import SequenceRepository
from src.game_period import beijing_now
from tests.fixture_support import make_account_environment


class TestAccountUIPolish(unittest.TestCase):
    def test_tacet_save_does_not_require_unlimited_forgery_and_keeps_inactive_mode(self):
        from PySide6.QtWidgets import QMessageBox
        from src.gui.AccountConfigTab import AccountTemplateDialog
        from src.task.forgery_quota_plan import FORGERY_MODE, FORGERY_GOALS
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            page = AccountConfigTab(AccountConfigEditor(env.repository))
            try:
                identity = page.selected_profile_id
                page._select_route('stamina')
                quota = page.form_widgets[FORGERY_GOALS]
                quota.mode.setCurrentIndex(quota.mode.findData('materials'))
                target = page.form_widgets['Which to Farm']
                target.setCurrentIndex(target.findData('Tacet Suppression'))
                self.assertTrue(page.form_rows[FORGERY_GOALS].isHidden())
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                    page.save()
                    self.drain(lambda: not page.operation.busy)
                self.assertIn('保存成功', page.status.text())
                saved = env.repository.load_profile(identity).tasks
                self.assertEqual('Tacet Suppression', saved['Which to Farm'])
                self.assertEqual('materials', saved[FORGERY_MODE])
                self.assertEqual([], saved[FORGERY_GOALS])
                dialog = AccountTemplateDialog(saved)
                try:
                    self.assertEqual(saved[FORGERY_MODE], dialog.tasks()[FORGERY_MODE])
                finally:
                    dialog.deleteLater()
                page.refresh()
                self.assertEqual('materials', page.form_widgets[FORGERY_GOALS].mode.currentData())
                target = page.form_widgets['Which to Farm']
                target.setCurrentIndex(target.findData('Forgery Challenge'))
                with self.assertRaisesRegex(ValueError, '至少一个领域目标'):
                    page._apply_text()
                self.assertEqual(saved, env.repository.load_profile(identity).tasks)
            finally:
                self.cleanup_page(page)

    def test_committed_slot_save_updates_label_order_and_keeps_uuid(self):
        from PySide6.QtWidgets import QMessageBox
        from src.account_slots import account_slot
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root, names=('A11', 'A10', 'A9', 'A1'))
            unassigned = next(r for r in env.repository.list_profiles() if r.account['short_name'] == 'A11')
            page = AccountConfigTab(AccountConfigEditor(env.repository))
            try:
                def codes():
                    return [page.profile_combo.itemText(i).split('-')[0] for i in range(page.profile_combo.count())]
                self.assertEqual(codes(), ['A1', 'A9', 'A10', '未分配'])
                page.profile_combo.setCurrentIndex(page.profile_combo.findData(unassigned.profile_id))
                widgets = dict(page.form_widgets)
                page.slot_editor.sequence.setCurrentIndex(page.slot_editor.sequence.findData('序列2'))
                page.slot_editor.slot.setCurrentIndex(page.slot_editor.slot.findData('B3'))
                self.assertTrue(page.profile_combo.currentText().startswith('未分配-'))
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                    page.save()
                    self.drain(lambda: not page.operation.busy)
                self.assertEqual(page.selected_profile_id, unassigned.profile_id)
                self.assertTrue(page.profile_combo.currentText().startswith('B3-'))
                self.assertEqual(codes(), ['A1', 'A9', 'A10', 'B3'])
                self.assertEqual(page.form_widgets, widgets)
                self.assertFalse(page.dirty)
                self.assertFalse(page.slot_editor.participating.isChecked())
                for sequence, slot, expected in (('序列1', 'A2', ['A1', 'A2', 'A9', 'A10']),
                                                  ('序列2', 'B10', ['A1', 'A9', 'A10', 'B10'])):
                    page.slot_editor.sequence.setCurrentIndex(page.slot_editor.sequence.findData(sequence))
                    page.slot_editor.slot.setCurrentIndex(page.slot_editor.slot.findData(slot))
                    with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                        page.save()
                        self.drain(lambda: not page.operation.busy)
                    self.assertEqual(codes(), expected)
                    self.assertEqual(page.selected_profile_id, unassigned.profile_id)
                    self.assertEqual(account_slot(env.repository.load_profile(unassigned.profile_id).account)['slot'], slot)
                page.refresh()
                self.assertEqual(codes(), expected)
                self.assertEqual(page.selected_profile_id, unassigned.profile_id)
                page.slot_editor.slot.setCurrentIndex(page.slot_editor.slot.findData('B4'))
                with patch.object(page.editor, 'save_draft', side_effect=OSError('synthetic save failure')), \
                     patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                    page.save()
                    self.drain(lambda: not page.operation.busy)
                self.assertIn('保存失败', page.status.text())
                self.assertTrue(page.profile_combo.currentText().startswith('B10-'))
                self.assertTrue(page.dirty)
            finally:
                self.cleanup_page(page)

    def test_external_choice_refresh_preserves_unsaved_editor(self):
        import copy
        from src.account_repository import ProfileEditScope
        from src.account_slots import SLOT_KEY
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            page = AccountConfigTab(AccountConfigEditor(env.repository))
            try:
                identity = page.selected_profile_id
                field = page.form_widgets['Record After Daily Task']
                value = not field.isChecked()
                field.setChecked(value)
                draft = page.draft
                other = env.repository.list_profiles()[1]
                account = copy.deepcopy(other.account)
                account['extensions'][SLOT_KEY] = {'sequence': '序列2', 'slot': 'B1'}
                env.repository.publish_profile(ProfileEditScope(other.profile_id, other.revision),
                                               {'account': account, 'tasks': other.tasks})
                page.refresh(preserve_draft=True)
                self.assertIs(page.draft, draft)
                self.assertEqual(page.selected_profile_id, identity)
                self.assertEqual(field.isChecked(), value)
                self.assertTrue(page.dirty)
                index = page.profile_combo.findData(other.profile_id)
                self.assertTrue(page.profile_combo.itemText(index).startswith('B1-'))
            finally:
                self.cleanup_page(page)

    def test_simplified_routes_inventory_form_and_reminder_rules_survive_save(self):
        from src.account_repository import ProfileEditScope
        from tests.TestForgeryQuotaPlan import goal
        from src.gui.ChoiceControls import QtComboBox
        from src.task.forgery_quota_plan import FORGERY_GOALS
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            record = env.repository.list_profiles()[0]
            tasks = dict(record.tasks)
            tasks.update({'Which to Farm': 'Forgery Challenge', 'Forgery Limit Mode': 'materials', FORGERY_GOALS: [dict(goal(1, 150),
                          inventory=dict(gold=0, purple=0, blue=0, green=25))]})
            account = dict(record.account)
            account.setdefault('extensions', {})['task_reminders'] = {'adversity_tower': {
                'enabled': True, 'rule': 'custom', 'reset_at': '2099-10-07T04:00:00+08:00',
                'priority': '中间塔优先', 'towers': ['回音之塔']}}
            env.repository.publish_profile(ProfileEditScope(record.profile_id, record.revision),
                                           {'account': account, 'tasks': tasks})
            page = AccountConfigTab(AccountConfigEditor(env.repository))
            page.resize(1080, 800)
            page.show()
            try:
                for hidden in ('forgery', 'tacet', 'daily_activity', 'merge_echo', 'closing', 'adversity_tower'):
                    self.assertNotIn(hidden, page._nav_items)
                self.assertIn('stamina', page._nav_items)
                for hidden in ('Merge Echo on Sunday', 'Logout After Daily Task'):
                    self.assertNotIn(hidden, page.form_widgets)
                page._select_route('stamina')
                self.app.processEvents()
                quota = page.form_widgets[FORGERY_GOALS]
                self.assertTrue(quota.goal_host.isVisible())
                self.assertTrue(page.form_rows['Which Tacet Suppression to Farm'].isVisible())
                self.assertFalse(page.form_rows['Which Forgery Challenge to Farm'].isVisible())
                quota.mode.setCurrentIndex(quota.mode.findData('unlimited'))
                self.app.processEvents()
                self.assertFalse(quota.goal_host.isVisible())
                self.assertFalse(page.form_rows['Which Tacet Suppression to Farm'].isVisible())
                self.assertTrue(page.form_rows['Which Forgery Challenge to Farm'].isVisible())
                page._select_route('weekly_boss')
                weekly = page.form_widgets['Weekly Boss Targets']
                self.assertIsInstance(weekly.rows[0][0], QtComboBox)
                page._select_route('reminder:adversity_tower')
                box, state, date = page.reminder_panel.task_choices['adversity_tower']
                self.assertEqual([state.itemText(i) for i in range(state.count())], ['完成', '未完成', '前置未完成'])
                self.assertFalse(date.isVisible())
                state.setCurrentIndex(state.findData('blocked'))
                page._apply_text()
                row = page.draft.account['extensions']['task_reminders']['adversity_tower']
                self.assertEqual('blocked', row['status'])
                self.assertEqual('2099-10-07T04:00:00+08:00', row['reset_at'])
                self.assertEqual(['回音之塔'], row['towers'])
                self.assertEqual('中间塔优先', row['priority'])
                self.assertEqual(150, page.draft.tasks[FORGERY_GOALS][0]['need']['green'])
            finally:
                self.cleanup_page(page)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from PySide6.QtGui import QFontDatabase
        font = Path('C:/Windows/Fonts/msyh.ttc')
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
        from src.gui.CodexTheme import apply_codex_light_theme
        apply_codex_light_theme(cls.app)

    def drain(self, predicate=lambda: True):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(.01)
        self.assertTrue(predicate())

    def cleanup_page(self, page):
        overview = page.account_tab.overview if hasattr(page, 'account_tab') else getattr(page, 'overview', page)
        overview.timer.stop()
        page.close()
        QThreadPool.globalInstance().waitForDone(5000)
        self.app.processEvents()
        page.deleteLater()
        self.app.processEvents()

    def test_account_switch_restores_draft_and_slot_conflict_is_inline(self):
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            env.repository.migrate_fixed_account_slots()
            page = AccountConfigTab(AccountConfigEditor(env.repository))
            try:
                field = page.form_widgets['Record After Daily Task']
                original = field.isChecked()
                field.setChecked(not original)
                origin = page.selected_profile_id
                page.profile_combo.setCurrentIndex(1)
                page.profile_combo.setCurrentIndex(0)
                self.assertEqual(page.selected_profile_id, origin)
                self.assertEqual(page.form_widgets['Record After Daily Task'].isChecked(), not original)
                self.assertTrue(page.dirty)
                self.assertEqual(env.repository.load_profile(origin).tasks.get('Record After Daily Task', original), original)
                page.slot_editor.slot.setCurrentIndex(page.slot_editor.slot.findData('A3'))
                self.assertIn('占用', page.slot_editor.error.text())
                with self.assertRaises(ValueError):
                    page._apply_text()
                page._load_selected(discard=True)
                self.assertFalse(page.dirty)
                self.assertEqual(page.slot_editor.slot.currentData(), 'A1')
            finally:
                self.cleanup_page(page)

    def test_rows_keep_focus_details_and_stale_snapshot_disables_writes(self):
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            page = AccountTaskOverview(env.repository, lambda: {})
            page.show()
            page.timer.stop()
            try:
                identity = env.repository.list_profiles()[0].profile_id
                page.set_profile(identity)
                self.drain(lambda: not page.loading.busy)
                cards = [AccountTaskCard('manual', '海墟提醒', 'pending', route='manual', manual=True)]
                page._cards = cards
                page._render(cards, beijing_now(), {})
                row = page._rows['manual']
                row.toggle.setChecked(True)
                row.settings.setFocus()
                page._render(cards, beijing_now(), {})
                self.assertIs(page._rows['manual'], row)
                self.assertTrue(row.toggle.isChecked())
                self.assertTrue(row.settings.hasFocus())
                changed = [replace(cards[0], state='completed', completed_at='2026-10-06T08:00:00+08:00')]
                page._cards = changed
                page._render(changed, beijing_now(), {})
                self.assertIs(page._rows['manual'], row)
                self.assertFalse(page._groups['completed'].content.isVisible())
                with patch.object(env.repository, 'load_profile', side_effect=OSError('synthetic unavailable')):
                    page.refresh(force=True)
                    self.drain(lambda: not page.loading.busy)
                self.assertIs(page._rows['manual'], row)
                self.assertIn('上次快照', page.notice.text())
                self.assertFalse(row.primary.isEnabled())
                page.set_profile(env.repository.list_profiles()[1].profile_id)
                self.assertFalse(page._rows)
                self.drain(lambda: not page.loading.busy)
                self.assertNotIn('manual', page._rows)
            finally:
                self.cleanup_page(page)

    def test_hidden_activity_failure_remains_visible_and_is_not_carried_to_next_account(self):
        from src.game_period import game_day_key
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            identities = [r.profile_id for r in env.repository.list_profiles()]
            env.integrity.set_progress('task_state_v1:' + identities[0], {'daily_activity': {
                'period_id': game_day_key(), 'result': 'failed', 'reason': '实测活跃度仅80'}})
            page = AccountTaskOverview(env.repository, lambda: {})
            page.show()
            page.timer.stop()
            try:
                page.set_profile(identities[0])
                self.drain(lambda: not page.loading.busy)
                self.assertNotIn('daily_activity', page._rows)
                self.assertIn('实测活跃度仅80', page.notice.text())
                self.assertTrue(page.notice.isVisible())
                page.set_profile(identities[1])
                self.assertEqual('', page._daily_notice)
                self.drain(lambda: not page.loading.busy)
                self.assertNotIn('实测活跃度仅80', page.notice.text())
            finally:
                self.cleanup_page(page)

    def test_late_read_after_a_b_a_switch_is_discarded(self):
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            page = AccountTaskOverview(env.repository, lambda: {})
            page.timer.stop()
            identities = [r.profile_id for r in env.repository.list_profiles()]
            started, release = threading.Event(), threading.Event()
            calls = []
            read = env.repository.load_profile
            def slow(identity):
                calls.append(identity)
                if len(calls) == 1:
                    started.set()
                    release.wait(3)
                return read(identity)
            try:
                with patch.object(env.repository, 'load_profile', side_effect=slow):
                    page.set_profile(identities[0])
                    self.assertTrue(started.wait(1))
                    page.set_profile(identities[1])
                    page.set_profile(identities[0])
                    release.set()
                    self.drain(lambda: len(calls) >= 2 and not page.loading.busy)
                self.assertEqual(calls, [identities[0], identities[0]])
                self.assertEqual(page.profile_id, identities[0])
                self.assertTrue(page._cards)
            finally:
                release.set()
                self.cleanup_page(page)

    def test_hub_fixed_slots_readonly_order_and_responsive_routes(self):
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            env.repository.migrate_fixed_account_slots()
            from src.account_repository import ProfileEditScope
            from tests.TestForgeryQuotaPlan import goal
            record = env.repository.list_profiles()[0]
            tasks = dict(record.tasks)
            tasks.update({'Which to Farm': 'Forgery Challenge', 'Forgery Limit Mode': 'materials',
                          'Forgery Material Goals': [dict(goal(1, 183),
                              inventory=dict(gold=1, purple=2, blue=3, green=4))]})
            env.repository.publish_profile(ProfileEditScope(record.profile_id, record.revision),
                                           {'account': record.account, 'tasks': tasks})
            with patch('src.gui.AccountSettingsTab.AccountConfigTab',
                       side_effect=lambda: AccountConfigTab(AccountConfigEditor(env.repository))), \
                 patch('src.gui.AccountSettingsTab.SequenceManagementTab',
                       side_effect=lambda *args, **kwargs: SequenceManagementTab(SequenceRepository(env.repository), **kwargs)):
                page = AccountSettingsTab()
            try:
                page.show()
                self.drain(lambda: not page.account_tab.overview.loading.busy)
                account = page.account_tab
                self.assertEqual([account.navigation.topLevelItem(i).text(0) for i in range(3)],
                                 ['任务总览', '账号序列', '账号执行顺序'])
                self.assertEqual(page.sequence_tab.members.count(), 10)
                self.assertEqual(page.order_tab.members.count(), 10)
                self.assertTrue(all(not page.order_tab.members.item(i).flags() & Qt.ItemIsUserCheckable for i in range(10)))
                self.assertTrue(all(page.order_tab.members.item(i).data(Qt.CheckStateRole) is None for i in range(10)))
                page.sequence_tab.members.item(3).setCheckState(Qt.Checked)
                self.drain(lambda: not page.sequence_tab.operation.busy)
                page.sequence_tab.members.item(2).setCheckState(Qt.Checked)
                self.drain(lambda: not page.sequence_tab.operation.busy)
                selected = env.repository.load_sequence('序列1').profile_ids
                self.assertEqual([env.repository.load_profile(identity).account['display_name'] for identity in selected], ['A3', 'A4'])
                from types import SimpleNamespace
                from ok import og
                snapshot = SequenceRepository(env.repository).create_run_snapshot('序列1')
                running = SimpleNamespace(running=True, _active_run_snapshot=snapshot,
                                          _run_profile_order=snapshot.profile_ids,
                                          _current_profile_id=selected[0], done_set=set())
                with patch.object(og, 'executor', SimpleNamespace(current_task=running), create=True):
                    page.order_tab.refresh()
                    self.assertIn('运行中', page.order_tab.members.item(2).text())
                    self.assertIn('下个账号', page.order_tab.members.item(3).text())
                    self.assertIn('本次运行快照', page.order_tab.snapshot_label.text())
                    self.assertFalse(page.order_tab.operation.busy)
                scale = float(os.environ.get('QT_SCALE_FACTOR', '1'))
                sizes = [(round(w / scale) - 96, round(h / scale) - 52) for w, h in
                         ((1280, 800), (1440, 900), (1920, 1080))] if os.environ.get('OKWW_UI_MATRIX') else ((720, 540), (1050, 720), (1700, 1000))
                for width, height in sizes:
                    page.resize(width, height)
                    for route in ('overview', 'sequences', 'sequence_order', 'identity', 'stamina', 'world_boss', 'weekly_boss', 'nightmare_nest', 'reminders', 'manual', 'reminder:adversity_tower'):
                        account._select_route(route)
                        self.drain()
                        self.assertLessEqual(page.width(), width + 2, (route, width, page.width()))
                        self.assertLessEqual(account.width(), page.viewport().width(), (route, width, account.width()))
                        self.assertLessEqual(account.view.width(), account.viewport().width(), (route, width, account.view.width()))
                        scroll = account.overview.scroll if route == 'overview' else account.settings_scroll
                        self.drain(lambda: scroll.widget().width() <= scroll.viewport().width())
                        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0, (width, route))
                        self.assertLessEqual(scroll.widget().width(), scroll.viewport().width(), (width, route, scroll.widget().width(), scroll.viewport().width()))
                    account._select_route('overview')
                    self.drain(lambda: not account.overview.loading.busy)
                    Path('test_out').mkdir(exist_ok=True)
                    page.grab().save(f'test_out/account-ui-polish-{width}-scale-{scale}.png')
            finally:
                self.cleanup_page(page)

    def test_embedded_sequence_collapse_releases_height_without_spreading_rows(self):
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            env.repository.migrate_fixed_account_slots()
            with patch('src.gui.AccountSettingsTab.AccountConfigTab',
                       side_effect=lambda: AccountConfigTab(AccountConfigEditor(env.repository))), \
                 patch('src.gui.AccountSettingsTab.SequenceManagementTab',
                       side_effect=lambda *args, **kwargs: SequenceManagementTab(SequenceRepository(env.repository), **kwargs)):
                page = AccountSettingsTab()
            try:
                page.show()
                self.drain(lambda: not page.account_tab.overview.loading.busy)
                account = page.account_tab
                scale = float(os.environ.get('QT_SCALE_FACTOR', '1'))
                sizes = [(round(w / scale) - 96, round(h / scale) - 52) for w, h in
                         ((1280, 800), (1440, 900), (1920, 1080))] if os.environ.get('OKWW_UI_MATRIX') else ((720, 540), (1050, 720), (1700, 1000))
                for width, height in sizes:
                    page.resize(width, height)
                    for route, editor in (('sequences', page.sequence_tab), ('sequence_order', page.order_tab)):
                        account._select_route(route)
                        editor.order_section.set_expanded(True)
                        for _ in range(5):
                            self.app.processEvents()
                        expanded_height = editor.view.height()
                        self.assertLessEqual(editor.order_section.header.height(), 72)
                        editor.order_section.set_expanded(False)
                        for _ in range(5):
                            self.app.processEvents()
                        Path('test_out').mkdir(exist_ok=True)
                        page.grab().save(f'test_out/sequence-collapse-{route}-{width}-scale-{scale}.png')
                        section = editor.order_section
                        self.assertLessEqual(section.header.height(), 72, (route, width, section.header.height()))
                        self.assertLessEqual(section.height(), section.header.height() + 34, (route, width, section.height()))
                        self.assertLessEqual(editor.help.height(), editor.help.sizeHint().height() + 4)
                        self.assertGreaterEqual(expanded_height - editor.view.height(), 300,
                                                (route, width, expanded_height, editor.view.height()))
                        account._select_route('identity')
                        account._select_route(route)
                        for _ in range(5):
                            self.app.processEvents()
                        self.assertFalse(section.content.isVisible())
                        self.assertLessEqual(section.header.height(), 72)
                        editor.order_section.set_expanded(True)
                        for _ in range(5):
                            self.app.processEvents()
                        self.assertTrue(editor.members.isVisible())
                        self.assertEqual(editor.members.count(), 10)
            finally:
                self.cleanup_page(page)

    def test_bookshelf_filters_include_waiting_and_keep_manual_actions_explicit(self):
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            page = AccountTaskOverview(env.repository, lambda: {})
            page.resize(1100, 850)
            page.show()
            page.timer.stop()
            try:
                cards = [AccountTaskCard('nightmare_nest', '残像聚落', 'pending', '所选聚落 1 / 2', route='nightmare_nest'),
                         AccountTaskCard('forgery', '凝素领域', 'running', '绿色当量 25 / 125', route='forgery'),
                         AccountTaskCard('tacet', '无音区', 'waiting', '等待前序任务', route='tacet'),
                         AccountTaskCard('weekly_boss', '战歌重奏', 'completed', completed_at='2026-10-06T08:00:00+08:00'),
                         AccountTaskCard('adversity_tower', '深塔', 'attention', '本期受阻关卡 1 个', route='adversity_tower'),
                         AccountTaskCard('manual', '海墟提醒', 'pending', route='manual', manual=True)]
                page._cards = cards
                page._render(cards, beijing_now(), {'elapsed': 42})
                self.app.processEvents()
                self.assertFalse(page._groups['completed'].content.isVisible())
                self.assertIn('42', page._rows['forgery'].time_label.text())
                page._set_filter('pending')
                self.app.processEvents()
                self.assertTrue(page._rows['tacet'].isVisible())
                self.assertTrue(page._rows['forgery'].isVisible())
                self.assertFalse(page._rows['weekly_boss'].isVisible())
                page._set_filter('attention')
                self.assertTrue(page._rows['adversity_tower'].isVisible())
                self.assertFalse(page._rows['manual'].isVisible())
                page._set_filter('completed')
                self.assertTrue(page._groups['completed'].content.isVisible())
                page._set_filter(None)
                launch = []
                page.launch_page.connect(launch.append)
                with patch.object(page, '_mark') as mark:
                    page._rows['manual'].primary.click()
                    mark.assert_called_once_with('manual', True)
                self.assertFalse(launch)
                self.assertEqual(page._rows['adversity_tower'].primary.text(), '单独启动')
                self.assertIn('08:00', page.recent.text())
                self.app.processEvents()
                page.grab().save('test_out/bookshelf-overview-states.png')
            finally:
                self.cleanup_page(page)

    def test_slot_delegate_preserves_native_keyboard_checks_and_readonly_order(self):
        from PySide6.QtTest import QTest
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            env.repository.migrate_fixed_account_slots()
            editor = SequenceManagementTab(SequenceRepository(env.repository))
            readonly = SequenceManagementTab(editor.service, readonly=True)
            editor.resize(1150, 1000)
            editor.show()
            try:
                editor.choice_buttons['序列2'].click()
                self.assertEqual(editor._selected().sequence_id, '序列2')
                editor.choice_buttons['序列1'].click()
                item = editor.members.item(2)
                identity = item.data(Qt.UserRole)
                checked = item.checkState() == Qt.Checked
                editor.members.setCurrentRow(2)
                editor.members.setFocus()
                self.app.processEvents()
                QTest.keyClick(editor.members, Qt.Key_Space)
                self.drain(lambda: not editor.operation.busy)
                selected = env.repository.load_sequence('序列1').profile_ids
                self.assertEqual(identity in selected, not checked)
                readonly.refresh()
                readonly.members.setCurrentRow(2)
                QTest.keyClick(readonly.members, Qt.Key_Space)
                self.app.processEvents()
                self.assertEqual(env.repository.load_sequence('序列1').profile_ids, selected)
                self.assertIsNone(readonly.members.item(2).data(Qt.CheckStateRole))
                legacy = editor.legacy_choice.findText('S1')
                self.assertGreaterEqual(legacy, 0)
                editor.legacy_choice.setCurrentIndex(legacy)
                self.assertEqual(editor._selected().sequence_id, 'S1')
                editor.choice_buttons['序列1'].click()
                self.app.processEvents()
                editor.grab().save('test_out/bookshelf-sequence-native.png')
            finally:
                for page in (editor, readonly):
                    page.live_timer.stop()
                    page.close()
                    page.deleteLater()
                QThreadPool.globalInstance().waitForDone(5000)
                self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
