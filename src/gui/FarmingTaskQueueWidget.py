"""Instance editor using the account hub's shared Fluent cards and form controls."""
from copy import deepcopy
from uuid import uuid4
from PySide6.QtCore import Signal, QTimer, Qt, QSignalBlocker
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QDialog, QDialogButtonBox, QScrollArea, QMessageBox, QInputDialog)
from qfluentwidgets import PushButton, PrimaryPushButton, DropDownPushButton, RoundMenu
from src.gui.ChoiceControls import QtComboBox
from src.gui.SectionPanel import SectionPanel
from src.gui.FlatSettingRow import FlatSettingRow
from src.gui.CodexTheme import SPACING, size_dialog
from src.gui.ForgeryQuotaWidget import ForgeryQuotaWidget
from src.task.farming_task_queue import (FARMING_TASKS, KINDS, farming_tasks, migrate_farming_tasks,
    new_task, project_task, task_group, task_order_key, task_status, task_progress, task_target_label)
from src.task.forgery_quota_plan import FORGERY_GOALS, FORGERY_MODE


class FarmingTaskDialog(QDialog):
    def __init__(self, item=None, service=None, profile_id=None, parent=None):
        super().__init__(parent)
        self.item = deepcopy(item)
        self.replacement_id = str(uuid4())
        self.service, self.profile_id = service, profile_id
        self.setWindowTitle('编辑刷取任务' if item else '添加刷取任务')
        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget(scroll)
        self.form = QVBoxLayout(host)
        self.form.setSpacing(SPACING['section'])
        self.name = QLineEdit(item['name'] if item else '', host)
        self.name.setPlaceholderText('例如：角色甲突破、角色乙技能、无音区保底')
        self.form.addWidget(FlatSettingRow('任务名称', self.name, parent=host))
        self.kind = QtComboBox(host)
        for value, title in KINDS.items():
            self.kind.addItem(title, value)
        self.kind.setCurrentIndex(self.kind.findData(item['kind'] if item else 'tacet'))
        self.kind.setEnabled(item is None)
        self.form.addWidget(FlatSettingRow('任务类型', self.kind, parent=host))
        self.params_host = QWidget(host)
        self.params_layout = QVBoxLayout(self.params_host)
        self.params_layout.setContentsMargins(0, 0, 0, 0)
        self.params_layout.setSpacing(SPACING['row'])
        self.form.addWidget(self.params_host)
        self.error = QLabel(host)
        self.error.setWordWrap(True)
        self.error.setProperty('role', 'error')
        self.form.addWidget(self.error)
        self.form.addStretch()
        scroll.setWidget(host)
        outer.addWidget(scroll)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Save).setText('确定')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.kind.currentIndexChanged.connect(self._build_params)
        self._build_params()
        size_dialog(self, 680, 620)

    def _build_params(self, *_):
        while self.params_layout.count():
            widget = self.params_layout.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        kind = self.kind.currentData()
        params = self.item['params'] if self.item else {}
        self.target = QtComboBox(self.params_host)
        if kind == 'world_boss':
            from src.task.world_boss_materials import TARGETS_BY_ID
            options = [(key, target.name) for key, target in TARGETS_BY_ID.items()]
        elif kind == 'weekly':
            from src.task.weekly_boss import WEEKLY_BOSSES, WEEKLY_AUTO
            options = [(b.key, b.name) for b in WEEKLY_BOSSES] + [(WEEKLY_AUTO, WEEKLY_AUTO)]
        elif kind == 'forgery':
            from src.task.forgery_targets import FORGERY_DOMAIN_OPTIONS
            options = FORGERY_DOMAIN_OPTIONS
        elif kind == 'tacet':
            from src.task.tacet_targets import TACET_OPTIONS
            options = TACET_OPTIONS
        else:
            options = [('Resonator EXP', '共鸣者经验'), ('Weapon EXP', '武器经验'), ('Shell Credit', '贝币')]
        for value, title in options:
            self.target.addItem(title, value)
        value = params.get('boss', params.get('domain', params.get('target', options[0][0])))
        self.target.setCurrentIndex(self.target.findData(value))
        self.params_layout.addWidget(FlatSettingRow('刷取目标', self.target,
            '更换关卡后，新目标从零累计；原领取记录保留。' if self.item else '', self.params_host))
        if kind in ('weekly', 'world_boss'):
            limit = params.get('limit', -1 if kind == 'weekly' else 1)
            self.limit = QLineEdit('不限' if limit == -1 else str(limit), self.params_host)
            self.params_layout.addWidget(FlatSettingRow('领取次数目标', self.limit,
                '累计成功领取次数，跨周保留；填写“不限”作为长期周本。' if kind == 'weekly' else
                '累计成功领取次数，跨日保留；达到目标后归入已完成。', self.params_host))
        elif kind == 'forgery':
            tasks = project_task(self.item) if self.item else {FORGERY_MODE: 'unlimited', FORGERY_GOALS: []}
            self.quota = ForgeryQuotaWidget(tasks, self.service, self.profile_id, self.params_host, max_goals=1)
            row = self.quota.rows[0]
            row['target'].setCurrentIndex(row['target'].findData(value))
            row['target'].hide()
            def select_domain(*_):
                row['target'].setCurrentIndex(row['target'].findData(self.target.currentData()))
                # The quota editor rejects a change while a claim is pending.
                with QSignalBlocker(self.target):
                    self.target.setCurrentIndex(self.target.findData(row['target'].currentData()))
            self.target.currentIndexChanged.connect(select_domain)
            self.params_layout.addWidget(self.quota)
        else:
            note = QLabel('不限次数；全部有限材料任务结束后，持续刷取到体力不足。', self.params_host)
            note.setWordWrap(True)
            note.setProperty('role', 'description')
            self.params_layout.addWidget(note)
        self.error.clear()

    def values(self):
        kind = self.kind.currentData()
        target = self.target.currentData()
        if kind in ('weekly', 'world_boss'):
            text = self.limit.text().strip()
            if kind == 'weekly' and text == '不限':
                limit = -1
            elif text.isascii() and text.isdecimal():
                limit = int(text)
            else:
                raise ValueError('领取次数请输入正整数' + ('，或填写“不限”' if kind == 'weekly' else ''))
            params = dict(boss=target, limit=limit)
        elif kind == 'forgery':
            params = dict(mode=self.quota.mode.currentData(), domain=target)
            if params['mode'] == 'materials':
                params['goal'] = self.quota.values()[0]
        else:
            params = dict(target=target)
        result = deepcopy(self.item) if self.item else new_task(kind, params)
        if self.item:
            previous = self.item['params']
            original_target = previous.get('boss', previous.get('domain', previous.get('target')))
            if target != original_target:
                result['id'] = self.replacement_id
                result.pop('legacy_progress', None)
        result.update(name=self.name.text().strip() or KINDS[kind], params=params)
        return farming_tasks({FARMING_TASKS: [result]})[0]

    def _accept(self):
        try:
            self.values()
        except ValueError as error:
            self.error.setText(str(error))
            return
        self.accept()


class FarmingTaskQueueWidget(QWidget):
    changed = Signal()

    def __init__(self, tasks, service=None, profile_id=None, parent=None):
        super().__init__(parent)
        config = deepcopy(tasks)
        migrate_farming_tasks(config)
        self.items = farming_tasks(config)
        self.service, self.profile_id = service, profile_id
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(0, 0, 0, 0)
        self.outer.setSpacing(SPACING['section'])
        tools = QHBoxLayout()
        self.add_button = PrimaryPushButton('添加任务', self)
        self.add_button.clicked.connect(lambda: self.edit())
        tools.addWidget(self.add_button)
        self.resolve_button = PushButton('核对未确认领取', self)
        self.resolve_button.clicked.connect(self.resolve_pending)
        tools.addWidget(self.resolve_button)
        tools.addStretch()
        self.outer.addLayout(tools)
        note = QLabel('周本 → 每日所选聚落 → 全部突破 → 全部凝素 → 无限保底。组内按顺序执行。\n'
                      '有限任务达标后归入已完成；修改后点击“确认保存”生效。', self)
        note.setWordWrap(True)
        note.setProperty('role', 'description')
        self.outer.addWidget(note)
        self.error = QLabel(self)
        self.error.setWordWrap(True)
        self.error.setProperty('role', 'error')
        self.error.hide()
        self.outer.addWidget(self.error)
        self.host = QWidget(self)
        self.host_layout = QVBoxLayout(self.host)
        self.host_layout.setContentsMargins(0, 0, 0, 0)
        self.host_layout.setSpacing(SPACING['section'])
        self.outer.addWidget(self.host)
        self._snapshot = None
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def values(self):
        return farming_tasks({FARMING_TASKS: self.items})

    def _journals(self):
        if not self.service or not self.profile_id:
            return []
        from src.task.world_boss_material_progress import WorldBossMaterialProgress
        from src.task.weekly_boss_progress import WeeklyBossProgress
        from src.task.forgery_quota_progress import ForgeryQuotaProgress
        result = []
        for cls in (WorldBossMaterialProgress, WeeklyBossProgress, ForgeryQuotaProgress):
            journal = cls(self.service, self.profile_id)
            for key in self.service.get_progress_entries(journal.key):
                instance = cls(self.service, self.profile_id)
                instance.key = key
                result.append(instance)
        return result

    def refresh(self):
        try:
            statuses = [task_status(item, self.service, self.profile_id) for item in self.items]
            pending = any(journal.pending() for journal in self._journals())
        except (ValueError, RuntimeError) as error:
            self.error.setText('领取记录读取失败：' + str(error))
            self.error.show()
            self.resolve_button.hide()
            return
        self.error.hide()
        self.resolve_button.setVisible(pending)
        snapshot = (deepcopy(self.items), statuses)
        if snapshot == self._snapshot:
            return
        self._snapshot = snapshot
        expanded = getattr(self, 'completed_group', None)
        expanded = bool(expanded and expanded.toggle_button.isChecked())
        while self.host_layout.count():
            widget = self.host_layout.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        groups = []
        for title in ('战歌重奏', '讨伐强敌', '凝素材料', '无限保底', '已完成'):
            group = SectionPanel(title, parent=self.host, collapsible=title == '已完成', expanded=expanded)
            group.set_flat()
            self.host_layout.addWidget(group)
            groups.append(group)
        self.completed_group = groups[-1]
        for index in sorted(range(len(self.items)), key=lambda index: task_order_key(self.items[index])):
            item, status = self.items[index], statuses[index]
            done, pending, detail, stamp = status
            group = groups[-1] if done and not pending else groups[task_group(item)]
            card = QWidget(group)
            card.setObjectName('accountTaskRow')
            card.setAttribute(Qt.WA_StyledBackground)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(*(SPACING['panel'],) * 4)
            layout.setSpacing(SPACING['row'])
            line = QHBoxLayout()
            name = QLabel(item['name'], card)
            name.setProperty('role', 'sectionTitle')
            name.setWordWrap(True)
            line.addWidget(name, 1)
            badge = QLabel('领取待核验' if pending else '已完成' if done else '待执行' if item['enabled'] else '已暂停', card)
            badge.setProperty('role', 'taskBadge')
            badge.setProperty('state', 'attention' if pending else 'completed' if done else 'pending')
            line.addWidget(badge)
            layout.addLayout(line)
            target_text = task_target_label(item)
            text = QLabel(target_text + ' · ' + detail + (f'\n完成于 {stamp}' if stamp else ''), card)
            text.setWordWrap(True)
            text.setProperty('role', 'description')
            layout.addWidget(text)
            actions = QHBoxLayout()
            edit = PushButton('编辑', card)
            edit.clicked.connect(lambda checked=False, index=index: self.edit(index))
            actions.addWidget(edit)
            more = DropDownPushButton('更多', card)
            menu = RoundMenu(parent=more)
            choices = [('暂停' if item['enabled'] else '恢复', lambda index=index: self.toggle(index)),
                       ('上移', lambda index=index: self.move(index, -1)),
                       ('下移', lambda index=index: self.move(index, 1)),
                       ('删除', lambda index=index: self.delete(index))]
            if item['kind'] in ('weekly', 'world_boss'):
                choices.insert(1, ('校正累计领取', lambda index=index: self.correct(index)))
            for title, callback in choices:
                action = QAction(title, menu)
                peers = [i for i, row in enumerate(self.items) if task_order_key(row) == task_order_key(item)]
                if title == '上移':
                    action.setEnabled(index != peers[0])
                elif title == '下移':
                    action.setEnabled(index != peers[-1])
                action.triggered.connect(lambda checked=False, callback=callback: callback())
                menu.addAction(action)
            more.setMenu(menu)
            actions.addWidget(more)
            actions.addStretch()
            layout.addLayout(actions)
            group.add_widget(card)
        for group in groups:
            group.setVisible(group.content_layout.count() > 1)
        if not self.items:
            groups[0].set_description('尚无刷取任务。点击“添加任务”设置材料目标或无限保底。')
            groups[0].show()

    def _edited(self):
        self.refresh()
        self.changed.emit()

    def edit(self, index=None):
        dialog = FarmingTaskDialog(self.items[index] if index is not None else None,
                                   self.service, self.profile_id, self)
        if dialog.exec() != QDialog.Accepted:
            return
        item = dialog.values()
        if index is None:
            self.items.append(item)
        else:
            self.items[index] = item
        self._edited()

    def toggle(self, index):
        self.items[index]['enabled'] = not self.items[index]['enabled']
        self._edited()

    def move(self, index, direction):
        item = self.items[index]
        indexes = [i for i, row in enumerate(self.items) if task_order_key(row) == task_order_key(item)]
        position = indexes.index(index) + direction
        if 0 <= position < len(indexes):
            other = indexes[position]
            self.items[index], self.items[other] = self.items[other], item
            self._edited()

    def delete(self, index):
        if QMessageBox.question(self, '删除刷取任务',
                f'删除“{self.items[index]["name"]}”？领取历史仍保留。',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.items.pop(index)
            self._edited()

    def _can_correct(self):
        from ok import og
        if getattr(getattr(og, 'executor', None), 'current_task', None) is not None:
            QMessageBox.information(self, '请先停止任务', '停止当前任务后再核对或校正领取。')
            return False
        return bool(self.service and self.profile_id)

    def correct(self, index):
        if not self._can_correct():
            return
        item = self.items[index]
        if item['params']['boss'] == '自动（列表首项）':
            return
        try:
            journal = task_progress(item, self.service, self.profile_id)
            count, accepted = QInputDialog.getInt(self, '校正累计领取', item['name'],
                journal.counts().get(item['params']['boss'], 0), 0, 999999)
            if accepted:
                journal.correct(item['params']['boss'], count)
                self.refresh()
        except (ValueError, RuntimeError) as error:
            QMessageBox.warning(self, '校正失败', str(error))

    def resolve_pending(self):
        if not self._can_correct():
            return
        try:
            for journal in self._journals():
                for event_id, event in journal.pending().items():
                    if 'goal_id' in event:
                        value, accepted = QInputDialog.getItem(self, '核对凝素领取',
                            f'领域 {event["domain"]} · {event["time"]}\n实际消耗体力：', ['0', '40', '80'], 0, False)
                        if not accepted:
                            return
                        journal.resolve(event_id, int(value))
                    else:
                        value = QMessageBox.question(self, '核对领取记录',
                            f'{event["boss"]} · {event["time"]}\n是否已实际领取？是计入一次；否确认未领取。',
                            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Cancel)
                        if value == QMessageBox.Cancel:
                            return
                        journal.resolve(event_id, value == QMessageBox.Yes)
            self.refresh()
        except (ValueError, RuntimeError) as error:
            QMessageBox.warning(self, '核对失败', str(error))
