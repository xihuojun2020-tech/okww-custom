from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractScrollArea, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, FluentIcon, LineEdit, ListWidget, MessageBoxBase, PushButton, SubtitleLabel,
    MessageBox,
)

from ok import og


class DailyProfileDialog(MessageBoxBase):
    """管理每日任务配置方案的对话框。

    支持：选择切换 / 新建 / 重命名 / 删除 每日任务配置方案。
    所有操作委托给传入的 task 对象执行（task 负责读写 daily_profiles.json 与刷新 GUI）。
    """

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.task = task
        self.profile_names = list(task.get_profile_names())
        self.current_name = task.get_active_profile_name()

        self.title_label = SubtitleLabel('每日任务配置方案', self)
        self.title_label.setWordWrap(True)
        self.viewLayout.addWidget(self.title_label)

        self.list_widget = ListWidget(self)
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.list_widget.itemDoubleClicked.connect(lambda item: self.switch_to(item.text()))
        self.refresh_list()

        # 右侧操作按钮
        self.new_button = PushButton(FluentIcon.ADD, '新建', self)
        self.new_button.clicked.connect(self.new_profile)
        self.rename_button = PushButton(FluentIcon.EDIT, '重命名', self)
        self.rename_button.clicked.connect(self.rename_profile)
        self.delete_button = PushButton(FluentIcon.DELETE, '删除', self)
        self.delete_button.clicked.connect(self.delete_profile)

        btn_layout = QVBoxLayout()
        btn_layout.addWidget(self.new_button)
        btn_layout.addWidget(self.rename_button)
        btn_layout.addWidget(self.delete_button)
        btn_layout.addStretch(1)

        list_layout = QHBoxLayout()
        list_layout.addWidget(self.list_widget, stretch=1)
        list_layout.addLayout(btn_layout)
        self.viewLayout.addLayout(list_layout)

        self.yesButton.setText('切换')
        self.cancelButton.setText('取消')
        self.yesButton.clicked.connect(self.switch_selected)
        self.widget.setMinimumWidth(460)
        self.widget.setMinimumHeight(360)
        self.list_widget.setCurrentRow(self.profile_names.index(self.current_name)
                                       if self.current_name in self.profile_names else 0)

    def refresh_list(self):
        self.profile_names = list(self.task.get_profile_names())
        self.list_widget.clear()
        for name in self.profile_names:
            self.list_widget.addItem(name)
        row_height = self.list_widget.sizeHintForRow(0) if self.list_widget.count() else 24
        self.list_widget.setFixedHeight(max(32, row_height * self.list_widget.count() + 8))

    def get_selected_name(self):
        current = self.list_widget.currentItem()
        return current.text() if current else None

    def switch_selected(self):
        name = self.get_selected_name()
        if name:
            self.switch_to(name)

    def switch_to(self, name):
        if name and name != self.current_name:
            self.task.switch_profile(name)
            self.current_name = name
        self.close()

    def new_profile(self):
        from ok.gui.tasks.ModifyListDialog import AddTextMessageBox
        w = AddTextMessageBox(self.window())
        w.titleLabel.setText('新建每日任务配置方案名称')
        w.yesButton.setText('确认')
        w.cancelButton.setText('取消')
        if w.exec():
            name = w.add_text_edit.text().strip()
            if not name:
                return
            if name in self.task.get_profile_names():
                from ok.gui.util.app import show_info_bar
                show_info_bar(self.window(), '配置方案已存在：{name}'.format(name=name))
                return
            self.task.create_profile(name)
            self.current_name = name
            self.refresh_list()

    def rename_profile(self):
        old = self.get_selected_name()
        if not old:
            return
        from ok.gui.tasks.ModifyListDialog import AddTextMessageBox
        w = AddTextMessageBox(self.window())
        w.titleLabel.setText('重命名配置方案')
        w.yesButton.setText('确认')
        w.cancelButton.setText('取消')
        w.add_text_edit.setText(old)
        if w.exec():
            new = w.add_text_edit.text().strip()
            if not new or new == old:
                return
            if new in self.task.get_profile_names():
                from ok.gui.util.app import show_info_bar
                show_info_bar(self.window(), '配置方案已存在：{name}'.format(name=new))
                return
            self.task.rename_profile(old, new)
            if self.current_name == old:
                self.current_name = new
            self.refresh_list()

    def delete_profile(self):
        name = self.get_selected_name()
        if not name:
            return
        w = MessageBox('删除配置方案',
                       '确定删除每日任务配置方案：{name}？'.format(name=name),
                       self.window())
        w.yesButton.setText('删除')
        w.cancelButton.setText('取消')
        if w.exec():
            self.task.delete_profile(name)
            if self.current_name == name:
                self.current_name = self.task.get_active_profile_name()
            self.refresh_list()
