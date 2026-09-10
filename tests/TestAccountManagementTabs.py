import unittest
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import inspect
from custom_ok.ok.gui.MainWindow import MainWindow
from src.gui.AccountSettingsTab import AccountSettingsTab
from src.gui.AccountConfigTab import AccountConfigTab, ClickOnlyComboBox
from src.gui.SequenceManagementTab import SequenceManagementTab
from src.gui.AccountChangeEvent import AccountChangeEvent
from PySide6.QtCore import QCoreApplication, QEvent, QThread, QThreadPool, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
from src.account_config_editor import AccountConfigEditor
from src.account_repository import ProfileRevisionConflict
from src.gui.BackgroundOperation import BackgroundOperation
from tests.fixture_support import make_account_environment


class TestAccountManagementTabs(unittest.TestCase):
    def test_save_preserves_widgets_and_updates_revision_without_reloading(self):
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(Path(temp))
            tab = AccountConfigTab(AccountConfigEditor(env.repository))
            tab.profile_combo.setCurrentIndex(1)
            field = tab.form_widgets['Farm Nightmare Nest for Daily Echo']
            field.setChecked(True)
            widgets = dict(tab.form_widgets)
            panels = dict(tab.form_sections)
            next(iter(panels.values())).set_expanded(True)
            tab.resize(760, 350)
            tab.show()
            self.app.processEvents()
            tab.verticalScrollBar().setValue(tab.verticalScrollBar().maximum())
            scroll_position = tab.verticalScrollBar().value()
            revision = tab.draft.revision
            events = []
            tab.changed.connect(events.append)
            try:
                with patch.object(tab, '_render_form', wraps=tab._render_form) as render, \
                     patch.object(tab.editor, 'load_draft', wraps=tab.editor.load_draft) as load, \
                     patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                    tab.save()
                    self._drain_until(lambda: not tab.operation.busy)
                    self.assertEqual(render.call_count, 0)
                    self.assertEqual(load.call_count, 0)
                self.assertEqual(tab.form_widgets, widgets)
                self.assertEqual(tab.form_sections, panels)
                self.assertTrue(next(iter(panels.values())).toggle_button.isChecked())
                self.assertEqual(tab.verticalScrollBar().value(), scroll_position)
                self.assertNotEqual(tab.draft.revision, revision)
                self.assertFalse(tab.dirty)
                self.assertFalse(events[0].choices_changed)
                self.assertTrue(env.repository.load_profile(tab.selected_profile_id).tasks[
                    'Farm Nightmare Nest for Daily Echo'])
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                    field.setChecked(False)
                    tab.save()
                    self._drain_until(lambda: not tab.operation.busy)
                self.assertIn('保存成功', tab.status.text())
                self.assertFalse(tab.dirty)
            finally:
                tab.deleteLater()

    def test_save_accepts_normalized_alias_without_rebuilding(self):
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(Path(temp))
            tab = AccountConfigTab(AccountConfigEditor(env.repository))
            tab.form_widgets['备用识别名称'].setCurrentText('使用')
            tab.form_widgets['备用识别名称内容'].setText(' UTEST0099A ')
            events = []
            tab.changed.connect(events.append)
            try:
                with patch.object(tab, '_render_form', wraps=tab._render_form) as render, \
                     patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                    tab.save()
                    self._drain_until(lambda: not tab.operation.busy)
                    self.assertEqual(render.call_count, 0)
                self.assertEqual(tab.form_widgets['备用识别名称内容'].text(), 'UTEST0099A')
                self.assertEqual(tab.draft.account['alternate_login_name'], 'UTEST0099A')
                self.assertTrue(events[0].choices_changed)
                self.assertFalse(tab.dirty)
            finally:
                tab.deleteLater()

    def test_explicit_refresh_loads_selected_account_once(self):
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(Path(temp))
            tab = AccountConfigTab(AccountConfigEditor(env.repository))
            tab.profile_combo.setCurrentIndex(1)
            try:
                with patch.object(tab.editor, 'load_draft', wraps=tab.editor.load_draft) as load:
                    tab.refresh()
                    self.assertEqual(load.call_count, 1)
            finally:
                tab.deleteLater()

    def test_unchanged_sequences_refresh_revision_without_rebuilding(self):
        from src.sequence_repository import SequenceRepository
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(Path(temp))
            tab = SequenceManagementTab(SequenceRepository(env.repository))
            member = tab.members.item(0)
            old_revision = tab._selected().revision
            editor = AccountConfigEditor(env.repository)
            draft = editor.load_draft(env.repository.list_profiles()[0].profile_id)
            draft.tasks['Farm Nightmare Nest for Daily Echo'] = True
            editor.save_draft(draft.scope, draft, confirmed_account_label=draft.account['display_name'])
            try:
                with patch.object(tab, '_show_members', wraps=tab._show_members) as render:
                    tab.refresh()
                    self.assertEqual(render.call_count, 0)
                self.assertIs(tab.members.item(0), member)
                self.assertNotEqual(tab._selected().revision, old_revision)
            finally:
                tab.deleteLater()

    def test_membership_save_still_refreshes_choices_and_sequence_once(self):
        from src.sequence_repository import SequenceRepository
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(Path(temp))
            tab = AccountConfigTab(AccountConfigEditor(env.repository))
            sequences = SequenceManagementTab(SequenceRepository(env.repository))
            events = []
            tab.changed.connect(events.append)
            tab.changed.connect(lambda _: sequences.refresh())
            tab.sequence_widgets['S1'].setChecked(False)
            try:
                with patch.object(sequences, '_show_members', wraps=sequences._show_members) as render, \
                     patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                    tab.save()
                    self._drain_until(lambda: not tab.operation.busy)
                    self.assertEqual(render.call_count, 1)
                self.assertTrue(events[0].choices_changed)
                self.assertNotIn(tab.selected_profile_id, sequences._selected().profile_ids)
                self.assertFalse(tab.dirty)
            finally:
                tab.deleteLater()
                sequences.deleteLater()

    def test_twelve_account_save_refresh_logs_timing_without_rebuilding(self):
        from src.sequence_repository import SequenceRepository
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(Path(temp), names=tuple(f'A{i}' for i in range(1, 13)))
            tab = AccountConfigTab(AccountConfigEditor(env.repository))
            sequences = SequenceManagementTab(SequenceRepository(env.repository))
            tab.profile_combo.setCurrentIndex(8)
            tab.changed.connect(lambda _: sequences.refresh())
            tab.form_widgets['Farm Nightmare Nest for Daily Echo'].setChecked(True)
            try:
                with patch.object(tab, '_render_form', wraps=tab._render_form) as form_render, \
                     patch.object(sequences, '_show_members', wraps=sequences._show_members) as member_render, \
                     patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes), \
                     self.assertLogs('src.gui.AccountConfigTab', level='INFO') as captured:
                    tab.save()
                    self._drain_until(lambda: not tab.operation.busy)
                self.assertEqual(form_render.call_count, 0)
                self.assertEqual(member_render.call_count, 0)
                timing = [line for line in captured.output if 'account_save_ui_refresh_ms=' in line]
                self.assertEqual(len(timing), 1)
                print('synthetic_12_accounts: ' + timing[0])
            finally:
                tab.deleteLater()
                sequences.deleteLater()

    def test_weekday_template_and_account_roundtrip_preserves_day(self):
        from src.gui.AccountConfigTab import AccountTemplateDialog
        for stored in ('Monday', '星期一', '周一'):
            dialog = AccountTemplateDialog({'Weekly Garden Check Day': stored})
            self.assertEqual(dialog._widgets['Weekly Garden Check Day'].currentText(), '星期一')
            self.assertEqual(dialog.tasks()['Weekly Garden Check Day'], 'Monday')
            dialog.deleteLater()
        dialog = AccountTemplateDialog({'Weekly Garden Check Day': 'invalid'})
        with self.assertRaises(ValueError):
            dialog.tasks()
        dialog.deleteLater()
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(Path(temp))
            tab = AccountConfigTab(AccountConfigEditor(env.repository))
            try:
                for stored in ('Monday', '星期一'):
                    tab.draft.tasks['Weekly Garden Check Day'] = stored
                    tab._render_form()
                    tab._apply_text()
                    self.assertEqual(tab.draft.tasks['Weekly Garden Check Day'], 'Monday')
                tab.draft.tasks['Weekly Garden Check Day'] = 'invalid'
                tab._render_form()
                with self.assertRaises(ValueError):
                    tab._apply_text()
            finally:
                tab.deleteLater()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _drain_until(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(predicate(), 'background operation did not finish')

    def test_slow_save_is_off_thread_single_submission_and_gui_result(self):
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(Path(temp))
            editor = AccountConfigEditor(env.repository)
            tab = AccountConfigTab(editor)
            real_save = editor.save_draft
            worker_threads, result_threads, ticks = [], [], []
            def save(*args, **kwargs):
                worker_threads.append(QThread.currentThread())
                time.sleep(0.5)
                return real_save(*args, **kwargs)
            tab.changed.connect(lambda _: result_threads.append(QThread.currentThread()))
            timer = QTimer()
            timer.setInterval(20)
            timer.timeout.connect(lambda: ticks.append(time.monotonic()))
            timer.start()
            try:
                with patch.object(editor, 'save_draft', side_effect=save), \
                        patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                    before = time.monotonic()
                    self.assertIsNotNone(tab.save())
                    self.assertLess(time.monotonic() - before, 0.2)
                    self.assertFalse(tab.save_button.isEnabled())
                    self.assertIsNone(tab.save())
                    self._drain_until(lambda: not tab.operation.busy)
                self.assertEqual(len(worker_threads), 1)
                self.assertIsNot(worker_threads[0], self.app.thread())
                self.assertEqual(result_threads, [self.app.thread()])
                self.assertGreater(len(ticks), 8)
                self.assertTrue(tab.save_button.isEnabled())
                self.assertIn('保存成功', tab.status.text())
            finally:
                timer.stop()
                tab.deleteLater()

    def test_failed_save_preserves_draft_and_delayed_result_does_not_switch_account(self):
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(Path(temp))
            tab = AccountConfigTab(AccountConfigEditor(env.repository))
            tab.task_editor.setPlainText(tab.task_editor.toPlainText().replace('Shell Credit', 'Resonance Potion'))
            origin = tab.selected_profile_id
            def failed(*args, **kwargs):
                time.sleep(0.1)
                raise ProfileRevisionConflict('synthetic version conflict')
            try:
                with patch.object(tab.editor, 'save_draft', side_effect=failed), \
                        patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                    tab.save()
                    submitted = tab.draft
                    tab.profile_combo.setCurrentIndex(1)
                    other = tab.selected_profile_id
                    self._drain_until(lambda: not tab.operation.busy)
                self.assertEqual(tab.selected_profile_id, other)
                self.assertIn('synthetic version conflict', tab.status.text())
                self.assertEqual(tab._failed_drafts[origin], submitted)
                tab.profile_combo.setCurrentIndex(0)
                self.assertEqual(tab.draft, submitted)
            finally:
                tab.deleteLater()

    def test_external_refresh_keeps_edited_form_and_pending_draft(self):
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(Path(temp))
            tab = AccountConfigTab(AccountConfigEditor(env.repository))
            try:
                field = tab.form_widgets['Farm Nightmare Nest for Daily Echo']
                field.setChecked(not field.isChecked())
                self.assertTrue(tab.dirty)
                draft = tab.draft
                tab.refresh(preserve_draft=True)
                self.assertIs(tab.draft, draft)
                self.assertIn('草稿已保留', tab.status.text())
            finally:
                tab.deleteLater()

    def test_destroyed_window_does_not_receive_late_worker_result(self):
        owner = QWidget()
        operation = BackgroundOperation(owner)
        started, release = threading.Event(), threading.Event()
        results = []
        def work():
            started.set()
            release.wait(2)
            return 'done'
        operation.start(work, results.append, results.append)
        self.assertTrue(started.wait(1))
        owner.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        release.set()
        QThreadPool.globalInstance().waitForDone(2000)
        self.app.processEvents()
        self.assertEqual(results, [])

    def test_import_preflight_and_commit_use_worker_but_confirmation_uses_gui(self):
        from src.task.DailyTask import DailyTask
        from src.account_config_bundle import AccountConfigBundleService
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_account_environment(root)
            service = AccountConfigBundleService(root)
            path = root / 'bundle.json'
            service.export_bundle(path)
            task = DailyTask.__new__(DailyTask)
            task._get_account_bundle_service = lambda: service
            task._ask_open_path = lambda: path
            task.log_info = lambda *args, **kwargs: None
            task.log_error = lambda *args, **kwargs: self.fail(str(args))
            gui_calls, disk_calls, errors = [], [], []
            task._confirm_bundle_import = lambda summary: gui_calls.append(QThread.currentThread()) or True
            task._refresh_gui = lambda: gui_calls.append(QThread.currentThread())
            owner = QWidget()
            operation = BackgroundOperation(owner)
            def runner(work, complete, *, changed=False):
                def measured():
                    disk_calls.append(QThread.currentThread())
                    time.sleep(0.1)
                    return work()
                return operation.start(measured, complete, errors.append)
            try:
                task.import_account_config(operation_runner=runner)
                self._drain_until(lambda: not operation.busy)
                self.assertEqual(errors, [])
                self.assertEqual(len(disk_calls), 2)
                self.assertTrue(all(thread is not self.app.thread() for thread in disk_calls))
                self.assertEqual(gui_calls, [self.app.thread(), self.app.thread()])
            finally:
                owner.deleteLater()

    def test_sequence_write_uses_worker_and_returns_selection_on_gui(self):
        from src.sequence_repository import SequenceRepository
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(Path(temp))
            service = SequenceRepository(env.repository)
            tab = SequenceManagementTab(service)
            original = service.publish
            worker = []
            def publish(*args, **kwargs):
                worker.append(QThread.currentThread())
                time.sleep(0.1)
                return original(*args, **kwargs)
            try:
                tab.members.setCurrentRow(0)
                with patch.object(service, 'publish', side_effect=publish):
                    tab._move(1)
                    self.assertFalse(tab.down_button.isEnabled())
                    tab._move(1)
                    self._drain_until(lambda: not tab.operation.busy)
                self.assertEqual(len(worker), 1)
                self.assertIsNot(worker[0], self.app.thread())
                self.assertEqual(tab.members.currentRow(), 1)
            finally:
                tab.deleteLater()

    def test_startup_backup_does_not_copy_on_gui_thread(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'configs').mkdir()
            owner = QWidget()
            owner.version = 'test'
            threads = []
            def create(_service):
                threads.append(QThread.currentThread())
                time.sleep(0.1)
                return None
            try:
                with patch('custom_ok.ok.gui.MainWindow.os.getcwd', return_value=str(root)), \
                        patch('src.storage.get_config_backup_dir', return_value=root / 'backups'), \
                        patch('src.config_backup.ConfigBackupService.create_daily_snapshot', create):
                    MainWindow.auto_backup_config(owner)
                    self._drain_until(lambda: not owner._startup_backup_operation.busy)
                self.assertEqual(len(threads), 1)
                self.assertIsNot(threads[0], self.app.thread())
            finally:
                owner.deleteLater()

    def test_tabs_are_owned_by_single_account_settings_hub(self):
        source = inspect.getsource(MainWindow.__init__)
        self.assertIn("AccountSettingsTab", source)
        self.assertNotIn("ScheduleTaskTab", source)
        self.assertEqual(AccountSettingsTab.name.fget(None), "账号")

    def test_user_facing_names_are_distinct(self):
        self.assertEqual(AccountConfigTab.name.fget(None), "账号配置")
        self.assertEqual(SequenceManagementTab.name.fget(None), "序列管理")

    def test_delete_labels_identify_the_object_being_changed(self):
        account_source = inspect.getsource(AccountConfigTab.__init__)
        sequence_source = inspect.getsource(SequenceManagementTab.__init__)
        self.assertIn("删除当前账号", account_source)
        self.assertIn("删除当前序列", sequence_source)
        self.assertIn("账号执行顺序", sequence_source)
        self.assertIn("上移账号", sequence_source)
        self.assertIn("下移账号", sequence_source)

    def test_account_page_exposes_template_and_new_account_actions(self):
        source = inspect.getsource(AccountConfigTab)
        self.assertIn("编辑新账号模板", source)
        self.assertIn("新建账号配置", source)
        self.assertIn("ClickOnlyComboBox(self.form_host)", source)

    def test_sequence_page_keeps_only_creation_deletion_and_member_order_actions(self):
        source = inspect.getsource(SequenceManagementTab)
        for text in ("新建序列", "删除当前序列", "上移账号", "下移账号"):
            self.assertIn(text, source)
        for text in ('QPushButton("复制"', 'QPushButton("重命名"', 'QPushButton("启用/停用"'):
            self.assertNotIn(text, source)

    def test_account_page_exposes_sequence_membership(self):
        source = inspect.getsource(AccountConfigTab)
        self.assertIn("所属序列", source)
        self.assertIn("sequence_ids", source)

    def test_primary_farm_dropdown_ignores_mouse_wheel(self):
        class Event:
            ignored = False

            def ignore(self):
                self.ignored = True

        event = Event()
        ClickOnlyComboBox.wheelEvent(None, event)
        self.assertTrue(event.ignored)

    def test_account_pages_enter_safe_state_when_master_is_missing(self):
        account_source = inspect.getsource(AccountConfigTab.refresh)
        sequence_source = inspect.getsource(SequenceManagementTab.refresh)
        self.assertIn("AccountRepositoryError", account_source)
        self.assertIn("账号仓库暂不可用", account_source)
        self.assertIn("AccountRepositoryError", sequence_source)
        self.assertIn("序列仓库暂不可用", sequence_source)

    def test_account_change_event_carries_stable_ids(self):
        event = AccountChangeEvent("profile_saved", "rev-2", ("profile-a1",), ("序列2",))
        self.assertEqual(event.profile_ids, ("profile-a1",))
        self.assertEqual(event.sequence_ids, ("序列2",))

    def test_account_settings_wires_child_changes_and_refreshes_siblings(self):
        source = inspect.getsource(AccountSettingsTab)
        self.assertIn("account_tab.changed.connect", source)
        self.assertIn("sequence_tab.changed.connect", source)
        self.assertIn("refresh_sequences", source)
        self.assertIn("account_changed.emit", source)

    def test_embedded_pages_use_full_available_width(self):
        section_source = inspect.getsource(__import__(
            "src.gui.SectionPanel", fromlist=["SectionPanel"]).SectionPanel)
        account_source = inspect.getsource(AccountSettingsTab)
        self.assertIn("setHorizontalPolicy(QSizePolicy.Policy.Expanding)", section_source)
        self.assertIn("takeWidget", section_source)
        self.assertIn("add_embedded_widget", account_source)


if __name__ == "__main__":
    unittest.main()
