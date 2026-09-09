"""Small, deterministic light theme used by the desktop shell."""

from PySide6.QtCore import QObject, QEvent
from PySide6.QtGui import QColor, QPalette, QFont
from PySide6.QtWidgets import QApplication, QComboBox, QAbstractSpinBox, QAbstractScrollArea
from qfluentwidgets import Theme, qconfig, setThemeColor


COLORS = {
    "window": "#FAFAFA",
    "panel": "#FFFFFF",
    "border": "#E5E7EB",
    "text": "#1F2328",
    "muted": "#656D76",
    "accent": "#0969DA",
    "success": "#1A7F37",
    "error": "#CF222E",
    "control_border": "#8C959F",
    "hover": "#F0F1F3",
    "pressed": "#E8EBEF",
    "disabled": "#F6F6F6",
    "accent_hover": "#075DBF",
    "accent_pressed": "#064FA3",
}

SPACING = {"small": 8, "row": 12, "section": 24}
TYPE_SIZE = {"body": 13, "description": 12, "section": 15, "page": 23}


def size_dialog(dialog, width, height):
    """Use logical screen space for resizable editor dialogs."""
    screen = dialog.screen().availableGeometry()
    dialog.resize(min(width, max(1, screen.width() - 32)),
                  min(height, max(1, screen.height() - 64)))


class PageWheelGuard(QObject):
    """Wheel scrolling must never change a numeric or selection setting."""
    def eventFilter(self, widget, event):
        if event.type() == QEvent.Wheel and isinstance(widget, (QComboBox, QAbstractSpinBox)):
            parent = widget.parentWidget()
            while parent is not None:
                if isinstance(parent, QAbstractScrollArea):
                    bar = parent.verticalScrollBar()
                    delta = event.pixelDelta().y() or event.angleDelta().y() / 120 * bar.singleStep() * 3
                    bar.setValue(bar.value() - round(delta))
                    break
                parent = parent.parentWidget()
            event.accept()
            return True
        return False


def codex_style_sheet() -> str:
    """Return the shared stylesheet; deliberately has no dark-mode branch."""
    return f"""
    QWidget {{ color: {COLORS['text']}; font-size: {TYPE_SIZE['body']}px; }}
    QAbstractScrollArea, QScrollArea, QFrame#view {{
        background: {COLORS['window']}; border: 0;
    }}
    QWidget#codexSection, QWidget#configSection {{
        background: transparent; border: 0;
        border-bottom: 1px solid {COLORS['border']};
    }}
    QGroupBox {{ border: 0; border-top: 1px solid {COLORS['border']};
        margin-top: 18px; padding-top: 18px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 0; }}
    QLabel[role="sectionTitle"] {{ font-size: {TYPE_SIZE['section']}px; font-weight: 600; }}
    QLabel[role="pageTitle"] {{ font-size: {TYPE_SIZE['page']}px; font-weight: 600; }}
    QLabel[role="error"] {{ color: {COLORS['error']}; }}
    QLabel[role="description"], .codex-description {{ color: {COLORS['muted']}; font-size: {TYPE_SIZE['description']}px; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {COLORS['panel']}; border: 1px solid {COLORS['control_border']};
        border-radius: 6px; padding: 6px 8px; min-height: 22px;
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
    QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {COLORS['accent']}; }}
    QPushButton {{ background: {COLORS['panel']}; border: 1px solid {COLORS['border']};
        border-radius: 6px; padding: 6px 12px; min-height: 22px; }}
    QPushButton:hover {{ background: {COLORS['hover']}; }}
    QPushButton:pressed {{ background: {COLORS['pressed']}; }}
    QPushButton:focus {{ border-color: {COLORS['accent']}; }}
    QPushButton:disabled {{ color: {COLORS['control_border']}; background: {COLORS['disabled']}; }}
    QPushButton[role="primary"] {{ background: {COLORS['accent']}; color: white; }}
    QPushButton[role="danger"] {{ color: {COLORS['error']}; }}
    QPushButton[role="primary"]:hover {{ background: {COLORS['accent_hover']}; }}
    QPushButton[role="primary"]:pressed {{ background: {COLORS['accent_pressed']}; }}
    QPushButton[role="primary"]:disabled {{ background: {COLORS['disabled']}; color: {COLORS['muted']}; }}
    QToolButton[role="disclosure"] {{ text-align: left; background: transparent;
        border: 1px solid transparent; border-radius: 6px; padding: 8px 4px;
        font-size: 15px; font-weight: 600; min-height: 24px; }}
    QToolButton[role="disclosure"]:hover {{ background: {COLORS['hover']}; }}
    QToolButton[role="disclosure"]:focus {{ border-color: {COLORS['accent']}; }}
    QToolButton[role="disclosure"]:pressed {{ background: {COLORS['pressed']}; }}
    QDialog {{ background: {COLORS['window']}; }}
    QRadioButton, QCheckBox {{ spacing: 8px; min-height: 28px; }}
    QToolTip {{ background: {COLORS['text']}; color: {COLORS['panel']}; border: 0; }}
    """


def apply_codex_light_theme(app: QApplication | None) -> None:
    """Force the palette and stylesheet to the light Codex values."""
    if app is None:
        return
    font = QFont(app.font())
    font.setFamilies(['Microsoft YaHei', 'Segoe UI', 'sans-serif'])
    app.setFont(font)
    setThemeColor(QColor(COLORS['accent']), save=False)
    try:
        qconfig.set(qconfig.theme, Theme.LIGHT)
    except Exception:
        qconfig.theme = Theme.LIGHT
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(COLORS["window"]))
    palette.setColor(QPalette.Base, QColor(COLORS["panel"]))
    palette.setColor(QPalette.AlternateBase, QColor(COLORS["window"]))
    palette.setColor(QPalette.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Button, QColor(COLORS["panel"]))
    palette.setColor(QPalette.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Highlight, QColor(COLORS["accent"]))
    palette.setColor(QPalette.HighlightedText, QColor(COLORS["panel"]))
    app.setPalette(palette)
    app.setStyleSheet(codex_style_sheet())
    if not hasattr(app, '_page_wheel_guard'):
        app._page_wheel_guard = PageWheelGuard(app)
        app.installEventFilter(app._page_wheel_guard)


__all__ = ["COLORS", "SPACING", "TYPE_SIZE", "size_dialog", "apply_codex_light_theme", "codex_style_sheet"]
