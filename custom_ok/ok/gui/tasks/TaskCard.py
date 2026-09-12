from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget, QSizePolicy, QMenu
from qfluentwidgets import FluentIcon, PrimaryPushButton, PushButton, SwitchButton, MessageBox

from ok import Logger, BaseTask, og
from ok.gui.Communicate import communicate
from ok.gui.common.OKIcon import OKIcon
from ok.gui.tasks.ConfigCard import ConfigCard

logger = Logger.get_logger(__name__)


class TaskCard(ConfigCard):
    def __init__(self, task: BaseTask, onetime, *, fluent_sample=False):
        config_type = dict(task.config_type or {})
        config_description = task.config_description
        if type(task).__name__ in ('DailyTask', 'MultiAccountDailyTask'):
            allowed = ({'方案序列', 'Daily Profile', '备用识别名称', '备用识别名称内容'}
                       if type(task).__name__ == 'DailyTask' else
                       {'当前序列', '当前执行账号', '当前序列账号'})
            config_type = {key: dict(value) if isinstance(value, dict) else value for key, value in config_type.items()}
            for key in set(task.config) | set(config_type):
                if key not in allowed:
                    config_type[key] = {'hidden': True}
            config_description = {key: '' for key in task.config}
            for value in config_type.values():
                if isinstance(value, dict):
                    value.pop('last_completed_provider', None)
        if type(task).__name__ in ('DailyTask', 'MultiAccountDailyTask'):
            config_type['Manage Daily Profiles'] = {'hidden': True}
            config_type['管理序列'] = {'hidden': True}
        description = '' if (type(task).__name__ in ('DailyTask', 'MultiAccountDailyTask') or
                              fluent_sample and type(task).__name__ in ('GardenTask', 'WeeklyBossTask', 'EventTask')) else task.description
        super().__init__(task, task.name, task.config, description, task.default_config, config_description,
                         config_type, config_icon=task.icon or FluentIcon.INFO)
        self.task = task
        if type(task).__name__ == 'PianoTeachingTask':
            from src.activity_catalog import ACTIVITIES
            self.card.titleLabel.setText(ACTIVITIES['piano_activity'])
        from src.evidence.model import TASK_PROJECTS
        self._evidence_project = TASK_PROJECTS.get(type(task).__name__)
        if self._evidence_project:
            self.card.setContextMenuPolicy(Qt.CustomContextMenu)
            self.card.customContextMenuRequested.connect(self.show_evidence_menu)
            self.card.setToolTip('右键：保存当前画面为证据')
        self.onetime = onetime
        self._compact_header()
        self.state_label = QLabel(self.card)
        self.state_label.setProperty('role', 'description')
        self.state_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.card.layout_row.insertWidget(self.card.layout_row.count() - 1, self.state_label)

        # Create a container widget for buttons with consistent 6px spacing
        self.button_container = QWidget()
        self.button_layout = QHBoxLayout(self.button_container)
        self.button_layout.setContentsMargins(0, 0, 0, 0)
        self.button_layout.setSpacing(8)
        self.button_container.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self.addWidget(self.button_container)

        self.waiting_label = QLabel(self)
        self.waiting_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.waiting_label.setMaximumWidth(360)
        self.waiting_label.hide()

        self.instructions_button = PushButton(FluentIcon.INFO, self.tr("Instructions"), self)
        self.instructions_button.clicked.connect(self.show_instructions)

        if getattr(self.task, 'is_custom', False):
            self.edit_button = PushButton(FluentIcon.EDIT, self.tr("Edit"), self)
            self.edit_button.clicked.connect(self.edit_clicked)
        else:
            self.edit_button = None

        if onetime:
            self.pause_button = PushButton(FluentIcon.PAUSE, self.tr("Pause"), self)
            self.pause_button.clicked.connect(self.pause_clicked)

            self.stop_button = PrimaryPushButton(OKIcon.STOP, self.tr("Stop"), self)
            self.stop_button.clicked.connect(self.stop_clicked)

            self.start_button = PrimaryPushButton(FluentIcon.PLAY, self.tr("Start"), self)
            self.start_button.clicked.connect(self.start_clicked)
            self.enable_button = None
        else:
            self.pause_button = None
            self.stop_button = None
            self.start_button = None
            self.enable_button = SwitchButton(parent=self)
            self.enable_button.setOnText(self.tr('Enabled'))
            self.enable_button.setOffText(self.tr('Disabled'))
            self.enable_button.checkedChanged.connect(self.check_changed)

        # Collect all buttons in display order
        self.all_buttons = [b for b in [
            self.pause_button,
            self.stop_button,
            self.start_button,
            self.enable_button,
        ] if b is not None]

        self.waiting_label.setWordWrap(True)
        self.viewLayout.addWidget(self.waiting_label)
        self.viewLayout.addWidget(self.instructions_button)
        if self.edit_button is not None:
            self.viewLayout.addWidget(self.edit_button)
        if getattr(task, 'instructions', None) or self.edit_button is not None:
            self._expand_enabled = True
            self.card.expandButton.show()

        self.update_buttons(self.task)
        communicate.task.connect(self.update_buttons)
        if fluent_sample:
            self._apply_fluent_sample()
        elif not onetime:
            self.rootLayout.setContentsMargins(0, 0, 0, 0)
            self.rootLayout.setSpacing(4)
            self.viewLayout.setContentsMargins(12, 6, 12, 8)
            self.viewLayout.setSpacing(4)
            for widget in self.config_widgets:
                layout = widget.layout() if callable(widget.layout) else widget.layout
                margins = layout.contentsMargins()
                layout.setContentsMargins(margins.left(), 4, margins.right(), 4)
                widget.setMinimumHeight(44)
        if type(task).__name__ in ('DailyTask', 'MultiAccountDailyTask') and self.reset_config is not None:
            self.reset_config.hide()

    def add_buttons(self):
        if type(self.task).__name__ not in ('DailyTask', 'MultiAccountDailyTask'):
            super().add_buttons()

    def show_evidence_menu(self, position):
        menu = QMenu(self)
        action = menu.addAction('保存当前画面为证据')
        if menu.exec(self.card.mapToGlobal(position)) == action:
            page = getattr(og.main_window, 'completion_check_tab', None)
            if page is not None:
                og.main_window.switchTo(page)
                page.capture_evidence(self._evidence_project)

    def _apply_fluent_sample(self):
        """Task-page pilot only; shared configuration and execution stay unchanged."""
        from src.gui.CodexTheme import COLORS
        from src.gui.navigation_sections import task_category
        from PySide6.QtCore import QSize
        import re
        # Display-only cleanup: task names remain stable for config and execution.
        self.card.titleLabel.setText(re.sub(r'^[^\w]+', '', self.card.titleLabel.text()))
        if not self.task.icon:
            icon = {'每日执行': FluentIcon.CALENDAR, '每周任务': FluentIcon.SYNC,
                    '声骸获取与整理': FluentIcon.BOOK_SHELF}.get(task_category(self.task), FluentIcon.GAME)
            self.card.icon_label.setPixmap(icon.icon().pixmap(QSize(20, 20)))
        self.setObjectName('fluentTaskSample')
        self.viewLayout.removeWidget(self.card.contentLabel)
        self.card.text_layout.addWidget(self.card.contentLabel)
        self.card.contentLabel.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._expand_enabled = bool(self.config_widgets or self.reset_config or
                                    self.task.show_create_shortcut or self.task.instructions or self.edit_button)
        self.card.expandButton.setVisible(self._expand_enabled)
        if not self._expand_enabled:
            self.card.layout_row.addSpacing(self.card.expandButton.width() + self.card.layout_row.spacing())
        self.setExpand(self.isExpand)
        self.rootLayout.setContentsMargins(0, 0, 0, 0)
        self.rootLayout.setSpacing(0)
        self.card.setMinimumHeight(56)
        self.card.layout_row.setContentsMargins(16, 8, 12, 8)
        self.viewLayout.setContentsMargins(16, 12, 16, 16)
        self.view.setObjectName('fluentTaskDetails')
        self.setStyleSheet(f'''
            QWidget#fluentTaskSample {{ background: {COLORS['panel']};
                border: 1px solid {COLORS['border']}; border-radius: 8px; }}
            QWidget#fluentTaskSample QWidget#disclosureHeader {{
                background: transparent; border: 0; border-radius: 8px; }}
            QWidget#fluentTaskSample QWidget#disclosureHeader:hover {{
                background: {COLORS['hover']}; }}
            QWidget#fluentTaskDetails {{ border: 0;
                border-top: 1px solid {COLORS['border']}; }}
        ''')

    def open_account_editor(self):
        # Navigation only: never reload the selected account or discard a draft.
        og.main_window.navigate_tab('accounts')
        from src.gui.SectionPanel import reveal_widget
        reveal_widget(og.main_window.account_settings_tab.account_tab.profile_combo)

    def open_sequence_editor(self):
        og.main_window.navigate_tab('accounts')
        from src.gui.SectionPanel import reveal_widget
        reveal_widget(og.main_window.account_settings_tab.section_panels[1])

    def _compact_header(self):
        """Use a wrapping title and description, not a fixed-height header."""
        self.card.titleLabel.setWordWrap(True)
        self.card.contentLabel.setWordWrap(True)

    def update_content(self):
        content = ""
        if self.onetime:
            waiting_for = og.executor.waiting_for_task(self.task)
            if waiting_for:
                content = self.tr("Waiting for {task_name} task to be completed").format(
                    task_name=og.app.tr(waiting_for.name)
                )
        self.waiting_label.setText(content)
        self.waiting_label.setToolTip(content)
        self.waiting_label.setVisible(bool(content))
        state = ('已暂停' if self.task.paused else '运行中' if self.task.running
                 else '等待中' if self.task.enabled and self.onetime
                 else '已启用' if self.task.enabled else '未运行' if self.onetime else '已关闭')
        self.state_label.setText(state)
        recovery = getattr(self.task, 'recovery_status', '')
        if recovery:
            self.state_label.setText(f'{state} · {recovery}')
        self.state_label.setVisible(bool(self.onetime or self.task.running or self.task.paused or recovery))
        if not self.onetime and recovery and not self.task.running and not self.task.paused:
            self.state_label.setText(recovery)

    def start_clicked(self):
        if self.task.enabled and self.task.paused:
            logger.info(f"resume paused task {self.task}")
            self.task.unpause()
            return
        if self.task.first_run_alert:
            if not self.task.config.get('_first_run_alert'):
                title = og.app.tr('Alert')
                content = og.app.tr(self.task.first_run_alert)
                from qfluentwidgets import Dialog
                w = Dialog(title, content, self.window())
                # w.cancelButton.setVisible(False)
                w.yesButton.setText(og.app.tr('Confirm'))
                w.cancelButton.setText(og.app.tr('Cancel'))
                w.setContentCopyable(True)
                if w.exec():
                    self.task.config['_first_run_alert'] = self.task.first_run_alert
                else:
                    return
        og.app.start_controller.start(self.task)

    def stop_clicked(self):
        self.task.disable()
        self.task.unpause()

    def pause_clicked(self):
        self.task.pause()

    def edit_clicked(self):
        from ok import og
        og.main_window.edit_task_tab.load_task(self.task)
        og.main_window.switchTo(og.main_window.edit_task_tab)

    def show_instructions(self):
        if instructions := getattr(self.task, 'instructions', None):
            import re
            from PySide6.QtCore import Qt
            from qfluentwidgets import Dialog
            # Auto-link plain URLs while preserving existing <a> tags
            parts = re.split(r'(<a\s[^>]*>.*?</a>)', instructions, flags=re.DOTALL)
            for i, part in enumerate(parts):
                if not part.startswith('<a '):
                    parts[i] = re.sub(r'(https?://[^\s<>"]+)', r'<a href="\1">\1</a>', part)
            html = ''.join(parts).replace('\n', '<br>')
            w = Dialog(self.task.name, "", self.window())
            w.setContentCopyable(True)
            w.cancelButton.hide()
            w.contentLabel.setTextFormat(Qt.RichText)
            w.contentLabel.setOpenExternalLinks(True)
            w.contentLabel.setTextInteractionFlags(Qt.TextBrowserInteraction)
            w.contentLabel.setText(html)
            w.exec()

    def delete_task(self):
        w = MessageBox(self.tr('Delete Task'), self.tr('Are you sure you want to delete {}').format(self.task.name),
                       self.window())
        if w.exec():
            logger.info('Yes button is pressed')
            og.task_manager.delete_task(self.task)
        else:
            logger.info('No button is pressed')

    def _rebuild_button_layout(self):
        """Remove all buttons from layout, then re-add only visible ones for consistent spacing."""
        # Remove all items from the layout without deleting them
        while self.button_layout.count():
            self.button_layout.takeAt(0)
        self.button_layout.addStretch(1)
        # Add back only the visible buttons
        for btn in self.all_buttons:
            if not btn.isHidden():
                self.button_layout.addWidget(btn)
                QWidget.setTabOrder(btn, self.card.expandButton)

    def update_buttons(self, task):
        if task == self.task or self.onetime:
            # Determine visibility for instructions button
            has_instructions = (type(self.task).__name__ not in ('DailyTask', 'MultiAccountDailyTask')
                                and bool(getattr(self.task, 'instructions', None)))
            self.instructions_button.setVisible(has_instructions)
            self.update_content()

            if self.onetime:
                if self.task.enabled:
                    if self.task.paused:
                        self.start_button.setText(self.tr("Resume"))
                        self.start_button.setVisible(True)
                        self.pause_button.setVisible(False)
                        self.stop_button.setVisible(True)
                    elif self.task.running:
                        self.start_button.setVisible(False)
                        self.stop_button.setVisible(True)
                        self.pause_button.setVisible(True)
                    else:
                        self.start_button.setVisible(False)
                        self.stop_button.setVisible(True)
                        self.pause_button.setVisible(False)
                else:
                    self.start_button.setText(self.tr("Start"))
                    self.start_button.setVisible(True)
                    self.pause_button.setVisible(False)
                    self.stop_button.setVisible(False)
            else:
                if self.enable_button:
                    with QSignalBlocker(self.enable_button):
                        self.enable_button.setChecked(task.enabled)

            self._rebuild_button_layout()

    def check_changed(self, checked):
        manual_control = getattr(self.task, 'set_enabled_from_ui', None)
        if callable(manual_control):
            manual_control(checked)
            return
        if checked:
            import threading
            threading.Thread(target=self.task.enable, name="TaskEnable").start()
        else:
            self.task.disable()
