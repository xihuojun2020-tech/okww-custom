"""Integer-backed dropdown used for named in-game list entries."""

from PySide6.QtGui import QFontMetrics
from qfluentwidgets import ComboBox

from ok import og
from ok.gui.common.design_system import control_width
from ok.gui.tasks.ConfigLabelAndWidget import ConfigLabelAndWidget


class LabelAndIntegerDropDown(ConfigLabelAndWidget):
    """Show friendly labels while persisting the original integer value."""

    def __init__(self, config_desc, options, config, key: str):
        super().__init__(config_desc, config, key)
        self.key = key
        self.value_by_text = {}
        self.text_by_value = {}
        labels = []
        for value, label in options:
            try:
                translated = og.app.tr(str(label))
            except Exception:
                translated = str(label)
            self.value_by_text[translated] = int(value)
            self.text_by_value[int(value)] = translated
            labels.append(translated)

        self.combo_box = ComboBox()
        self.combo_box.addItems(labels)
        self.combo_box.currentTextChanged.connect(self.text_changed)
        fm = QFontMetrics(self.combo_box.font())
        width = max((fm.horizontalAdvance(label) for label in labels), default=0)
        self.combo_box.setFixedWidth(control_width(width + 50))
        self.add_widget(self.combo_box)
        self.update_value()

    def text_changed(self, text):
        value = self.value_by_text.get(text)
        if value is not None:
            self.update_config(value)

    def update_value(self):
        value = self.config.get(self.key)
        text = self.text_by_value.get(value)
        if text is None:
            # Preserve an out-of-range legacy value instead of silently
            # changing persisted data.
            text = str(value) if value is not None else ""
        index = self.combo_box.findText(text)
        if index < 0 and text:
            self.combo_box.addItem(text, userData=value)
            self.value_by_text[text] = value
            self.text_by_value[value] = text
            index = self.combo_box.findText(text)
        if index >= 0:
            self.combo_box.blockSignals(True)
            self.combo_box.setCurrentIndex(index)
            self.combo_box.blockSignals(False)


__all__ = ["LabelAndIntegerDropDown"]
