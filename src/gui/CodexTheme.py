"""Small, deterministic light theme used by the desktop shell."""

from PySide6.QtCore import QObject, QEvent
from PySide6.QtGui import QColor, QPalette, QFont
from PySide6.QtWidgets import QApplication, QComboBox, QAbstractSpinBox, QAbstractScrollArea
from qfluentwidgets import Theme, qconfig, setThemeColor, ComboBox


COLORS = {
    "window": "#F5F7FA",
    "panel": "#FFFFFF",
    "border": "#E3E8EF",
    "text": "#253047",
    "muted": "#637083",
    "accent": "#356CE7",
    "success": "#1A7F37",
    "error": "#CF222E",
    "control_border": "#8C959F",
    "hover": "#F2F5FB",
    "pressed": "#DFEAFF",
    "disabled": "#F0F3F7",
    "accent_hover": "#2859C9",
    "accent_pressed": "#234CA2",
    "selection_bg": "#EDF2FF",
    "selection_border": "#E0E9FF",
    "selection_text": "#285ECB",
    "success_bg": "#EDF7F0",
    "error_bg": "#FFF0F2",
}

SPACING = {"small": 8, "row": 8, "section": 16, "panel": 16}
TYPE_SIZE = {"body": 14, "description": 12, "section": 15, "page": 20}


def size_dialog(dialog, width, height):
    """Use logical screen space for resizable editor dialogs."""
    screen = dialog.screen().availableGeometry()
    dialog.resize(min(width, max(1, screen.width() - 32)),
                  min(height, max(1, screen.height() - 64)))


class PageWheelGuard(QObject):
    """Wheel scrolling must never change a numeric or selection setting."""
    def eventFilter(self, widget, event):
        if event.type() == QEvent.Wheel and isinstance(widget, (QComboBox, ComboBox, QAbstractSpinBox)):
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
        background: {COLORS['panel']}; border: 1px solid {COLORS['border']}; border-radius: 12px;
    }}
    QWidget#codexSection[flat="true"] {{ background: transparent; border: 0; }}
    QWidget#disclosureHeader {{ background: transparent; border-radius: 8px; }}
    QWidget#disclosureHeader:hover {{ background: {COLORS['hover']}; }}
    QWidget#accountTaskRow, QWidget#accountOwnership {{ background: {COLORS['panel']};
        border: 1px solid {COLORS['border']}; border-radius: 10px; }}
    QLabel[role="taskBadge"] {{ border-radius: 6px; padding: 5px 10px;
        color: {COLORS['muted']}; background: {COLORS['disabled']}; }}
    QLabel[role="taskBadge"][state="running"] {{ color: {COLORS['selection_text']}; background: {COLORS['selection_bg']}; }}
    QLabel[role="taskBadge"][state="attention"] {{ color: {COLORS['error']}; background: {COLORS['error_bg']}; }}
    QLabel[role="taskBadge"][state="completed"] {{ color: {COLORS['success']}; background: {COLORS['success_bg']}; }}
    QGroupBox {{ border: 0; margin-top: 12px; padding-top: 8px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 0; }}
    QLabel[role="sectionTitle"] {{ font-size: {TYPE_SIZE['section']}px; font-weight: 600; }}
    QLabel[role="pageTitle"] {{ font-size: {TYPE_SIZE['page']}px; font-weight: 600; }}
    QLabel[role="error"] {{ color: {COLORS['error']}; }}
    QLabel[role="description"], .codex-description {{ color: {COLORS['muted']}; font-size: {TYPE_SIZE['description']}px; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {COLORS['panel']}; border: 1px solid {COLORS['control_border']};
        border-radius: 8px; padding: 8px 10px; min-height: 22px;
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
    QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {COLORS['accent']}; }}
    QPushButton {{ background: {COLORS['panel']}; border: 1px solid {COLORS['border']};
        border-radius: 8px; padding: 8px 12px; min-height: 22px; }}
    QPushButton:hover {{ background: {COLORS['hover']}; }}
    QPushButton:pressed {{ background: {COLORS['pressed']}; }}
    QPushButton:focus {{ border-color: {COLORS['accent']}; }}
    QPushButton:disabled {{ color: {COLORS['control_border']}; background: {COLORS['disabled']}; }}
    QPushButton[role="primary"] {{ background: {COLORS['accent']}; color: white; }}
    QPushButton[role="danger"] {{ color: {COLORS['error']}; }}
    QPushButton[role="primary"]:hover {{ background: {COLORS['accent_hover']}; }}
    QPushButton[role="primary"]:pressed {{ background: {COLORS['accent_pressed']}; }}
    QPushButton[role="primary"]:disabled {{ background: {COLORS['disabled']}; color: {COLORS['muted']}; }}
    QPushButton[role="filter"], QPushButton[role="sequenceChoice"] {{ text-align: left; }}
    QPushButton[role="filter"]:checked, QPushButton[role="sequenceChoice"]:checked {{
        background: {COLORS['selection_bg']}; border-color: {COLORS['selection_border']}; color: {COLORS['selection_text']}; }}
    QPushButton[role="link"] {{ color: {COLORS['selection_text']}; background: transparent; border-color: transparent; }}
    QPushButton[role="link"]:hover {{ background: {COLORS['hover']}; }}
    QPushButton[role="link"]:focus {{ border-color: {COLORS['accent']}; }}
    QToolButton[role="disclosure"] {{ text-align: left; background: transparent;
        border: 1px solid transparent; border-radius: 6px; padding: 0;
        min-height: 0; }}
    QToolButton[role="disclosure"]:hover {{ background: {COLORS['hover']}; }}
    QToolButton[role="disclosure"]:focus {{ border-color: {COLORS['accent']}; }}
    QToolButton[role="disclosure"]:pressed {{ background: {COLORS['pressed']}; }}
    QToolButton[role="rowDisclosure"] {{ background: transparent; color: {COLORS['selection_text']};
        border: 1px solid transparent; border-radius: 8px; padding: 6px; }}
    QToolButton[role="rowDisclosure"]:hover, QToolButton[role="rowDisclosure"]:checked {{ background: {COLORS['hover']}; }}
    QToolButton[role="rowDisclosure"]:focus {{ border-color: {COLORS['accent']}; }}
    QDialog {{ background: {COLORS['window']}; }}
    QDialog#diagnosticDetails QTabWidget::pane {{
        border: 1px solid {COLORS['border']}; background: {COLORS['panel']};
    }}
    QDialog#diagnosticDetails QTabBar::tab {{
        background: transparent; color: {COLORS['muted']}; padding: 8px 16px;
        border-bottom: 2px solid transparent;
    }}
    QDialog#diagnosticDetails QTabBar::tab:selected {{
        color: {COLORS['accent']}; border-bottom-color: {COLORS['accent']};
    }}
    QDialog#diagnosticDetails QTabBar::tab:hover {{ background: {COLORS['hover']}; }}
    QDialog#diagnosticDetails QTabBar::tab:focus {{ border: 1px solid {COLORS['accent']}; }}
    QDialog#diagnosticDetails QTableWidget {{
        background: {COLORS['panel']}; alternate-background-color: {COLORS['window']};
        border: 0; selection-background-color: {COLORS['accent']}; selection-color: {COLORS['panel']};
    }}
    QDialog#diagnosticDetails QTableWidget::item {{ padding: 4px 8px; }}
    QDialog#diagnosticDetails QHeaderView::section {{
        background: {COLORS['window']}; color: {COLORS['muted']};
        border: 0; border-bottom: 1px solid {COLORS['border']}; padding: 8px;
    }}
    QRadioButton, QCheckBox {{ spacing: 8px; min-height: 28px; }}
    QTreeWidget#accountTaskNavigation {{ background: {COLORS['panel']}; border: 1px solid {COLORS['border']};
        border-radius: 12px; padding: 8px; outline: 0; }}
    QTreeWidget#accountTaskNavigation::item {{ min-height: 34px; padding: 5px 8px;
        border: 1px solid transparent; border-radius: 8px; margin: 3px 0; }}
    QTreeWidget#accountTaskNavigation::item:hover {{ background: {COLORS['hover']}; }}
    QTreeWidget#accountTaskNavigation::item:selected {{ background: {COLORS['selection_bg']};
        color: {COLORS['selection_text']}; border: 1px solid {COLORS['selection_border']}; }}
    QTreeWidget#accountTaskNavigation::item:focus {{ border-color: {COLORS['accent']}; }}
    QTreeWidget#accountTaskNavigation::branch {{ background: {COLORS['panel']}; border: 0; }}
    QTreeWidget#accountTaskNavigation::branch:selected {{ background: {COLORS['panel']}; border: 0; }}
    QListWidget#sequenceMembers {{ background: transparent; border: 0; outline: 0; }}
    QListWidget#sequenceMembers::item {{ padding: 6px 8px; border-bottom: 1px solid {COLORS['border']}; }}
    QListWidget#sequenceMembers::item:selected {{ background: {COLORS['selection_bg']}; color: {COLORS['text']}; }}
    QListWidget#sequenceMembers::item:hover {{ background: {COLORS['hover']}; }}
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
