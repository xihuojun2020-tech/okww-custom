"""Device parameter forms; editing never creates a capture or input backend."""

from copy import deepcopy
from importlib import import_module

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QStackedWidget, QVBoxLayout, QWidget)


_BACKENDS = {
    'windows': ('Windows HWND', 'WindowsDevice', {'type': 'windows', 'hwnd': 0}),
    'mumu': ('MuMu SDK', 'MuMuDevice', {'type': 'mumu', 'install_dir': '', 'instance_index': 0}),
    'adb': ('Android ADB', 'AdbDevice', {'type': 'adb', 'serial': ''}),
    'replay': ('Frame replay', 'ReplayDevice', {'type': 'replay', 'frames': []}),
}
_FIELDS = {
    'windows': (('hwnd', 'HWND (decimal or 0x)', 'integer', 0),
                ('capture_method', 'Capture method', 'choice', 'WGC'),
                ('input_method', 'Input method', 'choice', 'SendInput'),
                ('launch_command', 'Launch command (one argument per line)', 'list', []),
                ('target_executable', 'Target executable (absolute path)', 'optional', '')),
    'mumu': (('install_dir', 'MuMu installation directory', 'text', ''),
             ('instance_index', 'Instance index', 'integer', 0),
             ('dll_path', 'MuMu SDK DLL path', 'optional', ''),
             ('package_name', 'Android package name (optional)', 'optional', ''),
             ('app_index', 'App index', 'integer', 0)),
    'adb': (('serial', 'ADB serial', 'text', ''),
            ('adb_path', 'ADB executable path', 'text', 'adb')),
    'replay': (('frames', 'Frame paths (one per line)', 'list', []),),
}
_CHOICES = {'capture_method': ('WGC', 'BitBlt_RenderFull', 'PrintWindow'),
            'input_method': ('SendInput', 'PostMessage')}


class DeviceEditor(QWidget):
    options_changed = Signal(dict)

    def __init__(self, parent=None, *, window_enumerator=None):
        super().__init__(parent)
        self._labels = {}
        self._label_widgets = []
        self._error_message = None
        self._window_prompt = 'Refresh to list visible windows'
        self._window_enumerator = window_enumerator
        self._loading = False
        self._dirty = set()
        self._saved = {}
        self._options = {}
        self.backend_select = QComboBox()
        self.pages = QStackedWidget()
        self.fields = {}
        self.capabilities_label = QLabel()
        self.capabilities_label.setWordWrap(True)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.window_select = QComboBox()
        self.window_select.addItem(self._window_prompt, None)
        self.refresh_button = QPushButton('Refresh windows')
        for kind, (title, _, _) in _BACKENDS.items():
            self.backend_select.addItem(title, kind)
            page = QWidget()
            form = QFormLayout(page)
            if kind == 'windows':
                row = QHBoxLayout()
                row.addWidget(self.window_select, 1)
                row.addWidget(self.refresh_button)
                form.addRow('Visible window', row)
                self._label_widgets.append(('Visible window', form.labelForField(row)))
            self.fields[kind] = {}
            for key, label, field_type, _ in _FIELDS[kind]:
                if field_type == 'choice':
                    field = QComboBox()
                    field.addItems(_CHOICES[key])
                elif field_type == 'list':
                    field = QPlainTextEdit()
                    field.setMaximumHeight(90)
                else:
                    field = QLineEdit()
                field.setObjectName(f'device_{kind}_{key}')
                self.fields[kind][key] = field
                signal = field.currentIndexChanged if field_type == 'choice' else field.textChanged
                signal.connect(lambda *args, name=key: self._field_changed(name))
                form.addRow(label, field)
                self._label_widgets.append((label, form.labelForField(field)))
            self.pages.addWidget(page)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow('Device backend', self.backend_select)
        self._label_widgets.append(('Device backend', form.labelForField(self.backend_select)))
        layout.addLayout(form)
        layout.addWidget(self.pages)
        layout.addWidget(self.capabilities_label)
        layout.addWidget(self.error_label)
        self.backend_select.currentIndexChanged.connect(self._backend_changed)
        self.refresh_button.clicked.connect(self.refresh_windows)
        self.window_select.currentIndexChanged.connect(self._window_changed)
        self.set_options({'type': 'replay', 'frames': []})

    def _text(self, text, **values):
        if 'field' in values:
            values['field'] = self._labels.get(values['field'], values['field'])
        return self._labels.get(text, text).format(**values) if values else self._labels.get(text, text)

    def _error(self, text, **values):
        self._error_message = (text, values)
        return self._text(text, **values)

    def apply_labels(self, labels):
        self._labels = labels
        for text, widget in self._label_widgets:
            widget.setText(self._text(text))
        for index, (title, _, _) in enumerate(_BACKENDS.values()):
            self.backend_select.setItemText(index, self._text(title))
        self.refresh_button.setText(self._text('Refresh windows'))
        self.window_select.setItemText(0, self._text(self._window_prompt))
        self.capabilities_label.setText(self._text('Capabilities: {capabilities}',
            capabilities=', '.join(sorted(self.capabilities()))))
        if self.error_label.text() and self._error_message is not None:
            text, values = self._error_message
            self.error_label.setText(self._text(text, **values))

    def set_options(self, options: dict):
        if not isinstance(options, dict) or not isinstance(options.get('type'), str):
            raise ValueError(self._text('Device options must be a JSON object with a type'))
        kind = options['type']
        if kind not in _BACKENDS:
            raise ValueError(self._text('Unknown device type: {kind}', kind=kind))
        self._loading = True
        try:
            self._options = deepcopy(options)
            self._saved[kind] = deepcopy(options)
            self._dirty.clear()
            index = self.backend_select.findData(kind)
            self.backend_select.setCurrentIndex(index)
            self.pages.setCurrentIndex(index)
            for key, _, field_type, default in _FIELDS[kind]:
                value = options.get(key, default)
                if field_type == 'list':
                    text = '\n'.join(value) if value is not None else ''
                else:
                    text = str(value if value is not None else '')
                field = self.fields[kind][key]
                if field_type == 'choice':
                    field.setCurrentIndex(field.findText(text))
                elif field_type == 'list':
                    field.setPlainText(text)
                else:
                    field.setText(text)
            self.error_label.clear()
            self.capabilities_label.setText(self._text('Capabilities: {capabilities}',
                capabilities=', '.join(sorted(self.capabilities()))))
            if kind == 'windows':
                self._select_hwnd(options.get('hwnd', 0))
        finally:
            self._loading = False

    def options(self) -> dict:
        result = deepcopy(self._options)
        kind = result['type']
        for key, label, field_type, _ in _FIELDS[kind]:
            if key not in self._dirty:
                continue
            field = self.fields[kind][key]
            text = (field.currentText() if field_type == 'choice' else
                    field.toPlainText() if field_type == 'list' else field.text())
            if field_type == 'integer':
                try:
                    value = int(text, 16 if text.lower().startswith('0x') else 10)
                except ValueError as error:
                    raise ValueError(self._error('{field} must be an integer', field=label)) from error
                if key == 'hwnd' and value < 0:
                    raise ValueError(self._error('{field} cannot be negative', field=label))
                result[key] = value
            elif field_type == 'list':
                if key == 'launch_command' and not text:
                    result.pop(key, None)
                else:
                    result[key] = text.splitlines()
            elif field_type == 'optional' and not text:
                result.pop(key, None)
            else:
                result[key] = text
        return result

    def capabilities(self) -> frozenset:
        kind = self._options['type']
        module = import_module(f'gameframe.devices.{kind}')
        capabilities = getattr(module, _BACKENDS[kind][1]).capabilities
        if kind == 'windows' and self._options.get('input_method') == 'PostMessage':
            capabilities = capabilities - {'relative-mouse'}
        return capabilities

    def _field_changed(self, key):
        if self._loading:
            return
        self._dirty.add(key)
        self._emit_options()

    def _emit_options(self):
        try:
            options = self.options()
        except ValueError as error:
            self.error_label.setText(str(error))
            return
        self.error_label.clear()
        self._options = deepcopy(options)
        self.capabilities_label.setText(self._text('Capabilities: {capabilities}',
            capabilities=', '.join(sorted(self.capabilities()))))
        if options['type'] == 'windows':
            self._select_hwnd(options.get('hwnd', 0))
        self.options_changed.emit(options)

    def _backend_changed(self, index):
        if self._loading:
            return
        kind = self.backend_select.itemData(index)
        try:
            self._saved[self._options['type']] = self.options()
        except ValueError as error:
            self.error_label.setText(str(error))
            self._loading = True
            self.backend_select.setCurrentIndex(self.backend_select.findData(self._options['type']))
            self._loading = False
            return
        self.set_options(self._saved.get(kind, _BACKENDS[kind][2]))
        self._emit_options()

    def refresh_windows(self):
        try:
            enumerator = self._window_enumerator
            if enumerator is None:
                from gameframe.devices.windows import enumerate_windows
                enumerator = enumerate_windows
            windows = enumerator()
        except Exception as error:
            self.error_label.setText(self._error('Window enumeration failed: {error}', error=str(error)))
            return
        self.window_select.blockSignals(True)
        try:
            self.window_select.clear()
            self._window_prompt = 'Select a window or enter HWND below'
            self.window_select.addItem(self._text(self._window_prompt), None)
            for window in windows:
                self.window_select.addItem(
                    f"{window['title']} — PID {window['pid']} — HWND {window['hwnd']:#x}", window['hwnd'])
        finally:
            self.window_select.blockSignals(False)
        self._select_hwnd(self._options.get('hwnd', 0))
        self.error_label.clear()

    def _select_hwnd(self, hwnd):
        self.window_select.blockSignals(True)
        try:
            index = self.window_select.findData(hwnd)
            self.window_select.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self.window_select.blockSignals(False)

    def _window_changed(self, index):
        hwnd = self.window_select.itemData(index)
        if hwnd is not None:
            self.fields['windows']['hwnd'].setText(str(hwnd))
