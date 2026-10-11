"""Explicit user-operated Windows scheduler management."""
import json
from datetime import datetime, timedelta

from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QVBoxLayout, QWidget)
from src.native_schedule import NativeSchedule, schedulable_tasks
from src.runtime.native_language import translate


class NativeScheduleTab(QWidget):
    def __init__(self, package, data_dir, schema=None, parent=None, *, backend=None):
        super().__init__(parent)
        self.backend = backend or NativeSchedule(package, data_dir)
        self.records = []
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(translate('交互用户：{user}\n包：{package}\n数据：{data_dir}').format(
            user=self.backend.user, package=self.backend.package, data_dir=self.backend.data_dir)))
        self.items = QListWidget()
        layout.addWidget(self.items)
        self.task = QComboBox()
        self.trigger = QComboBox()
        for label, value in [('一次', 'once'), ('每天', 'daily'), ('每周一', 'weekly'),
                             ('每月1日', 'monthly'), ('间隔天', 'days'), ('间隔小时', 'hours')]:
            self.trigger.addItem(translate(label), value)
        self.start = QLineEdit((datetime.now() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0).isoformat())
        self.interval = QSpinBox()
        self.interval.setRange(1, 999)
        self.timeout = QSpinBox()
        self.timeout.setRange(0, 999)
        self.enabled = QCheckBox(translate('启用'))
        self.enabled.setChecked(True)
        self.device = QPlainTextEdit()
        self.device.setMaximumHeight(90)
        self.device.setPlainText(json.dumps(self.backend.launcher_device(), ensure_ascii=False))
        form = QFormLayout()
        for label, widget in [('任务', self.task), ('触发', self.trigger), ('本地开始时间 ISO', self.start),
                              ('间隔', self.interval), ('最长运行小时（0无限制）', self.timeout),
                              ('设备 JSON（必填）', self.device), ('', self.enabled)]:
            form.addRow(translate(label) if label else '', widget)
        layout.addLayout(form)
        self.preview_text = QPlainTextEdit()
        self.preview_text.setReadOnly(True)
        layout.addWidget(self.preview_text)
        buttons = QHBoxLayout()
        for label, handler in [('刷新', self.refresh), ('新建表单', self.clear_selection),
                               ('预览', self.preview), ('创建/更新', self.save), ('删除', self.delete)]:
            button = QPushButton(translate(label))
            button.clicked.connect(lambda checked=False, action=handler: self._act(action))
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.items.currentRowChanged.connect(self.select)
        self.set_schema(schema or [])

    def set_schema(self, schema):
        previous = self.task.currentData()
        self.task.clear()
        for task in schedulable_tasks(schema):
            self.task.addItem(task['name'], task['id'])
        index = self.task.findData(previous)
        if index >= 0:
            self.task.setCurrentIndex(index)

    def _act(self, action):
        try:
            action()
        except Exception as error:
            QMessageBox.critical(self, translate('计划任务失败'), str(error))

    def refresh(self):
        self.records = self.backend.list()
        self.items.clear()
        for record in self.records:
            notice = ' | ' + translate(record['migration_notice']) if record.get('requires_migration') else ''
            self.items.addItem(translate('{task} | {trigger} | {next_run} | 结果 {last_result}').format(
                task=record['binding']['task_id'], trigger=record['binding']['trigger'],
                next_run=record['next_run'], last_result=record['last_result']) + notice)

    def clear_selection(self):
        self.items.setCurrentRow(-1)

    def select(self, row):
        if row < 0:
            return
        record = self.records[row]
        binding = record['binding']
        self.task.setCurrentIndex(self.task.findData(binding['task_id']))
        self.trigger.setCurrentIndex(self.trigger.findData(binding['trigger']))
        self.start.setText(binding['start'])
        self.interval.setValue(binding['interval'])
        self.timeout.setValue(binding['timeout_hours'])
        self.enabled.setChecked(record['enabled'])
        self.device.setPlainText(json.dumps(binding['device'], ensure_ascii=False))
        self.preview_text.setPlainText(record['xml'])

    def _preview(self):
        if self.task.currentData() is None:
            raise ValueError(translate('请选择可计划执行的任务'))
        return self.backend.preview(self.task.currentData(), json.loads(self.device.toPlainText()),
            start=self.start.text(), trigger=self.trigger.currentData(), interval=self.interval.value(),
            enabled=self.enabled.isChecked(), timeout_hours=self.timeout.value())

    def preview(self):
        value = self._preview()
        self.preview_text.setPlainText(value['command'] + ' ' + value['arguments'] + '\n\n' + value['xml'])

    def save(self):
        row = self.items.currentRow()
        name = self.records[row]['name'] if row >= 0 else None
        saved_name = self.backend.create(self._preview(), name=name)
        self.refresh()
        QMessageBox.information(self, translate('计划任务已保存'),
            translate('更新成功：{name}' if name else '创建成功：{name}').format(name=saved_name))

    def delete(self):
        row = self.items.currentRow()
        if row >= 0:
            record = self.records[row]
            answer = QMessageBox.question(self, translate('删除计划任务'),
                translate('删除计划 {name}？\n任务：{task}').format(
                    name=record['name'], task=record['binding']['task_id']),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            self.backend.delete(record['name'])
            self.refresh()
