"""Long values use a dedicated editor instead of nested page scrolling."""
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout, QPushButton
from ok.gui.tasks.ConfigLabelAndWidget import ConfigLabelAndWidget


class LabelAndTextEdit(ConfigLabelAndWidget):
    def __init__(self, config_desc, config, key):
        super().__init__(config_desc, config, key)
        self.text_edit = QPlainTextEdit(self)
        self.text_edit.hide()
        self.edit_button = QPushButton('编辑内容…', self)
        self.add_widget(self.edit_button)
        self.update_value()
        self.text_edit.textChanged.connect(self.value_changed)
        self.edit_button.clicked.connect(self.edit_value)

    def update_value(self):
        self.text_edit.blockSignals(True)
        self.text_edit.setPlainText(str(self.config.get(self.key) or ''))
        self.text_edit.blockSignals(False)
        self.edit_button.setToolTip(self.text_edit.toPlainText()[:300])

    def value_changed(self):
        self.update_config(self.text_edit.toPlainText())
        self.edit_button.setToolTip(self.text_edit.toPlainText()[:300])

    def edit_value(self):
        dialog = QDialog(self.window())
        dialog.setWindowTitle(self.title.text())
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit(dialog)
        editor.setPlainText(self.text_edit.toPlainText())
        layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(640, 420)
        if dialog.exec() == QDialog.Accepted:
            self.text_edit.setPlainText(editor.toPlainText())
        dialog.deleteLater()
