"""Draft-only fixed-slot ownership editor; never writes on navigation."""
from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QPushButton
from src.gui.ChoiceControls import QtComboBox
from src.account_slots import FIXED_SEQUENCES, SLOT_KEY, account_slot, slots_for, slot_owners
from src.account_display import account_display_label


class AccountSlotEditor(QWidget):
    edited = Signal()
    order_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel('账号归属', self))
        self.sequence = QtComboBox(self)
        self.sequence.addItem('未分配', None)
        for key, (title, _) in FIXED_SEQUENCES.items():
            self.sequence.addItem(title, key)
        self.slot = QtComboBox(self)
        self.sequence.setAccessibleName('账号所属序列')
        self.slot.setAccessibleName('账号固定槽位')
        row.addWidget(self.sequence)
        row.addWidget(self.slot)
        row.addStretch(1)
        order = QPushButton('查看执行顺序', self)
        order.clicked.connect(self.order_requested)
        layout.addLayout(row)
        self.participating = QCheckBox('参与该序列执行', self)
        footer = QHBoxLayout()
        footer.addWidget(self.participating)
        footer.addStretch(1)
        footer.addWidget(order)
        layout.addLayout(footer)
        self.error = QLabel('', self)
        self.error.setWordWrap(True)
        self.error.setProperty('role', 'error')
        layout.addWidget(self.error)
        self._accounts, self._identity, self._changed = {}, None, False
        self.sequence.currentIndexChanged.connect(self._sequence_changed)
        self.slot.currentIndexChanged.connect(self._edit)
        self.participating.toggled.connect(self._edit)

    def load(self, account, accounts, identity, memberships):
        self._accounts, self._identity, self._changed = accounts, identity, False
        self._had_key = SLOT_KEY in account.get('extensions', {})
        try:
            assignment = account_slot(account)
        except ValueError:
            assignment = None
        with QSignalBlocker(self.sequence), QSignalBlocker(self.participating):
            self.sequence.setCurrentIndex(max(0, self.sequence.findData(assignment['sequence'] if assignment else None)))
            self._populate(assignment['slot'] if assignment else None)
            self.participating.setChecked(bool(assignment and assignment['sequence'] in memberships))
        self._validate()

    def _populate(self, selected=None):
        with QSignalBlocker(self.slot):
            self.slot.clear()
            sequence = self.sequence.currentData()
            if sequence:
                for slot in slots_for(sequence):
                    self.slot.addItem(slot, slot)
                self.slot.setCurrentIndex(max(0, self.slot.findData(selected)))
            self.slot.setEnabled(bool(sequence))
            self.participating.setEnabled(bool(sequence))

    def _sequence_changed(self, *_):
        self._populate()
        self._edit()

    def _validate(self):
        assignment = self.assignment()
        error = ''
        if assignment:
            try:
                owners = slot_owners(self._accounts, assignment['sequence']).get(assignment['slot'], [])
                others = [identity for identity in owners if identity != self._identity]
                if others:
                    error = f"{assignment['slot']} 已被 {account_display_label(self._accounts[others[0]])} 占用，请选择空槽位。"
            except ValueError as exc:
                error = str(exc)
        self.error.setText(error)
        self.error.setVisible(bool(error))
        return error

    def _edit(self, *_):
        self._changed = True
        self._validate()
        self.edited.emit()

    def assignment(self):
        sequence = self.sequence.currentData()
        return {'sequence': sequence, 'slot': self.slot.currentData()} if sequence else None

    def apply(self, account, boxes):
        if not self._changed:
            return
        error = self._validate()
        if error:
            raise ValueError(error)
        assignment = self.assignment()
        account.setdefault('extensions', {})[SLOT_KEY] = assignment
        for key in FIXED_SEQUENCES:
            if key in boxes:
                with QSignalBlocker(boxes[key]):
                    boxes[key].setChecked(bool(assignment and assignment['sequence'] == key and self.participating.isChecked()))
