from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout


class FlowLayout(QWidget):
    def __init__(self, alignment=Qt.AlignLeft):
        super().__init__()
        self.setWindowTitle("Flow Layout")
        self.alignment = alignment

        # Main vertical layout
        self.vbox = QVBoxLayout()
        self.setLayout(self.vbox)

        # Add the first horizontal layout
        self.add_new_hbox()

    def add_new_hbox(self):
        # Create a new horizontal layout and add it to the vertical layout
        self.hbox = QHBoxLayout()
        self.hbox.setAlignment(self.alignment)
        self.vbox.addLayout(self.hbox)
        self.current_width = 0

    def add_widget(self, widget):
        # Measure the width of the widget
        widget_width = widget.sizeHint().width()

        # Only wrap when the layout has a real width; during early layout
        # passes width() may be the tiny default, which would wrongly force
        # every widget onto its own line and make text look truncated.
        layout_width = self.width()
        if layout_width > 100 and self.current_width + widget_width > layout_width:
            self.add_new_hbox()

        # Add the widget to the current horizontal layout
        self.hbox.addWidget(widget)
        self.current_width += widget_width
