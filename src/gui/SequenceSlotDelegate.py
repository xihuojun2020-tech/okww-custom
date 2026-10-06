"""Column-aligned slots retaining native checkbox and keyboard behavior."""
from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyleOptionButton, QStyle
from src.gui.CodexTheme import COLORS


class SequenceSlotDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(0, 64) if index.data(Qt.UserRole + 2) else super().sizeHint(option, index)

    def paint(self, painter, option, index):
        data = index.data(Qt.UserRole + 2)
        if not data:
            return super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style()
        painter.save()
        painter.setClipRect(opt.rect)
        style.drawPrimitive(QStyle.PE_PanelItemViewItem, opt, painter, opt.widget)
        left = opt.rect.left() + 10
        if index.data(Qt.CheckStateRole) is not None:
            check = QStyleOptionButton()
            check.rect = style.subElementRect(QStyle.SE_ItemViewItemCheckIndicator, opt, opt.widget)
            check.state = (QStyle.State_Enabled if opt.state & QStyle.State_Enabled else QStyle.State_None)
            check.state |= QStyle.State_On if index.data(Qt.CheckStateRole) == Qt.Checked.value else QStyle.State_Off
            style.drawControl(QStyle.CE_CheckBox, check, painter, opt.widget)
            left = check.rect.right() + 12
        width = opt.rect.right() - left - 10
        def label(x, y, w, value, color=COLORS['text']):
            painter.setPen(QColor(color))
            painter.drawText(QRect(x, y, max(0, w), 24), Qt.AlignVCenter | Qt.AlignLeft,
                             opt.fontMetrics.elidedText(value, Qt.ElideRight, max(0, w)))
        status = data.get('live') or data['status']
        status_color = COLORS['selection_text'] if data.get('live') or data.get('selected') else COLORS['muted']
        if width >= 700:
            account_width = width - 400
            label(left, opt.rect.top() + 20, 56, data['slot'])
            label(left + 66, opt.rect.top() + 20, account_width, data['label'])
            label(left + 76 + account_width, opt.rect.top() + 20, 132, status, status_color)
            label(left + 218 + account_width, opt.rect.top() + 20, 182, data['summary'], COLORS['muted'])
        else:
            label(left, opt.rect.top() + 6, 48, data['slot'])
            label(left + 58, opt.rect.top() + 6, width - 58, data['label'])
            label(left + 58, opt.rect.top() + 33, width - 58,
                  status + (' · ' + data['summary'] if data['summary'] else ''), status_color)
        painter.setPen(QColor(COLORS['border']))
        painter.drawLine(opt.rect.bottomLeft(), opt.rect.bottomRight())
        if opt.state & QStyle.State_HasFocus:
            painter.setPen(QColor(COLORS['accent']))
            painter.drawRoundedRect(opt.rect.adjusted(1, 1, -2, -2), 6, 6)
        painter.restore()
