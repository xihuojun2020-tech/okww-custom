from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from ok.gui.tasks.ConfigLabelAndWidget import ConfigLabelAndWidget


class LabelAndLabel(ConfigLabelAndWidget):
    """只读信息标签：展示任务的动态信息（如各子任务上次完成时间），不写回配置。

    与 config_type 中 `{'type': 'label'}` 配合使用。若绑定的 task 提供
    get_last_completed()，且 config_type 中指定了 sub_key，则显示该子任务
    的上次完成时间；否则显示 config 中该键的值。
    通过 communicate.task 信号在任务开始/结束时自动刷新（跨线程安全）。
    """

    def __init__(self, config_desc, config, key, task=None, sub_key=None):
        super().__init__(config_desc, config, key)
        self.task = task
        self.sub_key = sub_key
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.add_widget(self.label, stretch=1)
        self.update_value()
        if task is not None:
            from ok.gui.Communicate import communicate
            communicate.task.connect(self._on_task_state)

    def _on_task_state(self, task):
        if task is self.task:
            self.update_value()

    def update_value(self):
        if self.task is not None and self.sub_key and hasattr(self.task, 'get_last_completed'):
            ts = self.task.get_last_completed(self.sub_key)
            self.label.setText(ts if ts else '')
        elif self.task is not None and hasattr(self.task, 'get_last_completed_display'):
            text = self.task.get_last_completed_display()
            self.label.setText(text or '')
        else:
            text = self.config.get(self.key)
            self.label.setText(text or '')
