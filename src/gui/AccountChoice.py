"""Account dropdown with display labels separate from persisted values."""
from PySide6.QtCore import QSignalBlocker
from ok.gui.tasks.ConfigLabelAndWidget import ConfigLabelAndWidget
from src.gui.AccountConfigTab import ClickOnlyComboBox
from src.account_display import account_option_labels


class AccountChoice(ConfigLabelAndWidget):
    def __init__(self, config_desc, options, config, key):
        super().__init__(config_desc, config, key)
        self.combo_box = ClickOnlyComboBox()
        self.set_options(options)
        self.combo_box.currentIndexChanged.connect(self._selected)
        self.add_widget(self.combo_box)

    def _selected(self, index):
        if index >= 0:
            self.update_config(self.combo_box.itemData(index))

    def update_value(self):
        with QSignalBlocker(self.combo_box):
            values = [self.combo_box.itemData(i) for i in range(self.combo_box.count())]
            for index, label in enumerate(account_option_labels(values)):
                self.combo_box.setItemText(index, label)
            self.combo_box.setCurrentIndex(self.combo_box.findData(self.config.get(self.key)))

    def set_options(self, options):
        values = list(options)
        with QSignalBlocker(self.combo_box):
            self.combo_box.clear()
            for value, label in zip(values, account_option_labels(values)):
                self.combo_box.addItem(label, value)
            self.combo_box.setCurrentIndex(self.combo_box.findData(self.config.get(self.key)))
