from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, FluentIcon, ScrollArea

from ok.gui.widget.CustomTab import CustomTab


class PermanentEventTab(CustomTab):
    """常驻活动：自动化的常驻玩法（暂为空占位，预留扩展）。"""

    def __init__(self):
        super().__init__()
        container = QWidget(self.view)
        layout = QVBoxLayout(container)
        layout.setAlignment(Qt.AlignTop)

        layout.addWidget(BodyLabel(self.tr('常驻活动')))
        layout.addWidget(BodyLabel(self.tr(
            '此分类用于放置长期可玩的活动（如固定周常、月常副本）。'
            '当前尚未添加任何自动化任务，后续可按需扩展。'
        )))

        self.add_widget(container)

    @property
    def name(self):
        return '常驻活动'

    @property
    def icon(self):
        return FluentIcon.CALORIES

    @property
    def position(self):
        from qfluentwidgets import NavigationItemPosition
        return NavigationItemPosition.SCROLL