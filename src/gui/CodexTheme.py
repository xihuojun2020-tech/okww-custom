"""Small, deterministic light theme used by the desktop shell."""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication
from qfluentwidgets import Theme, qconfig


COLORS = {
    "window": "#F7F8FA",
    "panel": "#FFFFFF",
    "border": "#E5E7EB",
    "text": "#1F2328",
    "muted": "#656D76",
    "accent": "#0969DA",
    "success": "#1A7F37",
    "error": "#CF222E",
}


def codex_style_sheet() -> str:
    """Return the shared stylesheet; deliberately has no dark-mode branch."""
    return f"""
    QWidget {{ color: {COLORS['text']}; font-size: 13px; }}
    QAbstractScrollArea, QScrollArea, QFrame#view {{
        background: {COLORS['window']}; border: 0;
    }}
    QGroupBox, QFrame[frameShape="4"], QWidget#codexSection {{
        background: {COLORS['panel']};
        border: 1px solid {COLORS['border']};
        border-radius: 10px;
    }}
    QLabel[role="description"], .codex-description {{ color: {COLORS['muted']}; font-size: 12px; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {COLORS['panel']}; border: 1px solid {COLORS['border']};
        border-radius: 6px; padding: 5px 8px;
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
    QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {COLORS['accent']}; }}
    QPushButton, qfluentwidgets--PushButton {{ border-radius: 6px; padding: 5px 10px; }}
    QToolTip {{ background: {COLORS['text']}; color: {COLORS['panel']}; border: 0; }}
    """


def apply_codex_light_theme(app: QApplication | None) -> None:
    """Force the palette and stylesheet to the light Codex values."""
    if app is None:
        return
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


__all__ = ["COLORS", "apply_codex_light_theme", "codex_style_sheet"]
