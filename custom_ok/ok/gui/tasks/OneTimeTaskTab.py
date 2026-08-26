from ok import Logger, og

from ok.gui.tasks.TaskCard import TaskCard
from ok.gui.tasks.TaskTab import TaskTab

logger = Logger.get_logger(__name__)


class OneTimeTaskTab(TaskTab):
    def __init__(self, is_standalone=True, group_name=None, section=None, activity_category=None):
        super().__init__()
        self.is_standalone = is_standalone
        self.group_name = group_name
        self.section = section
        self.activity_category = activity_category
        self.card_widgets = []
        self.keep_info_when_done = True
        
        # Check if this is an imported script to show delete button
        self.imported_file_name = None
        for fn, imp in og.task_manager.imported_scripts.items():
            if imp['script_name'] == self.group_name:
                self.imported_file_name = fn
                break
                
        if self.imported_file_name:
            from PySide6.QtWidgets import QHBoxLayout, QSpacerItem, QSizePolicy, QWidget
            from qfluentwidgets import PushButton, FluentIcon
            
            self.button_container = QWidget()
            self.btn_layout = QHBoxLayout(self.button_container)
            self.btn_layout.setContentsMargins(0, 10, 0, 0)
            self.btn_layout.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
            
            self.delete_btn = PushButton(self.tr('Delete Script'), self, FluentIcon.DELETE)
            self.delete_btn.clicked.connect(self.delete_script)
            self.btn_layout.addWidget(self.delete_btn)
            
            # Keep this ordinary footer outside the expandable-card layout.
            self.vBoxLayout.addWidget(self.button_container)
            
        from ok.gui.Communicate import communicate
        communicate.task_list_updated.connect(self.refresh_ui)
        self.refresh_ui()

        # 运行日志常驻面板（任务页底部：任务开始后实时显示账号/阶段中文日志）
        from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget
        self.log_panel_text = QPlainTextEdit()
        self.log_panel_text.setReadOnly(True)
        self.log_panel_text.setMaximumBlockCount(800)
        self.log_panel_text.setPlaceholderText('运行日志将在这里实时显示（任务执行时逐阶段提示）')
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 8, 0, 0)
        log_layout.addWidget(self.log_panel_text)
        self.vBoxLayout.addWidget(log_widget)
        communicate.log.connect(self._append_log)

    def _append_log(self, level_no, message):
        """把运行日志追加到常驻日志面板（communicate.log 信号）。"""
        try:
            # Window geometry churn is an internal capture diagnostic, not a
            # task-stage message. Keep it in the file log but hide it from the
            # user-facing task panel to avoid flooding the UI.
            if 'do_update_window_size changed' in str(message):
                return
            self.log_panel_text.appendPlainText(message)
            sb = self.log_panel_text.verticalScrollBar()
            sb.setValue(sb.maximum())
        except Exception:
            pass

    def delete_script(self):
        from qfluentwidgets import MessageBox
        w = MessageBox(self.tr('Confirm Delete'), 
                       self.tr('Are you sure you want to delete the script "{}"?').format(self.group_name), 
                       self.window())
        if w.exec():
            og.task_manager.delete_imported_script(self.imported_file_name)

    def refresh_ui(self):
        # Remove old cards
        for w in self.card_widgets:
            self.remove_task_card(w)
            w.deleteLater()
        self.card_widgets.clear()
        
        self.tasks = []
        for task in og.executor.onetime_tasks:
            if not getattr(task, 'visible', True):
                continue
            task_group = getattr(task, 'group_name', None)
            if self.section:
                from src.gui.navigation_sections import classify_task
                if classify_task(task) == self.section and (
                        self.activity_category is None or
                        getattr(task, 'activity_category', task_group) == self.activity_category):
                    self.tasks.append(task)
            elif self.is_standalone and not task_group:
                self.tasks.append(task)
            elif self.group_name and task_group == self.group_name:
                self.tasks.append(task)
                
        for task in self.tasks:
            task_card = TaskCard(task, True)
            self.card_widgets.append(task_card)
            self.add_task_card(task_card)

    def in_current_list(self, task):
        return getattr(self, 'tasks', None) and task in self.tasks
