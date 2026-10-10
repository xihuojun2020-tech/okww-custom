# SPDX-License-Identifier: MIT
"""Generic image patch renderer over a verified physical client rectangle."""
import base64
import ctypes
from ctypes import wintypes
import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget


class WindowsOverlayGeometry:
    """Read-only target identity and physical geometry, without capture or input."""
    def __init__(self, backend=None):
        if backend is None:
            from gameframe.devices.windows import _WindowBackend
            backend = _WindowBackend()
        self.backend = backend
        backend.user32.GetDpiForWindow.argtypes = (wintypes.HWND,)
        backend.user32.GetDpiForWindow.restype = wintypes.UINT
        backend.user32.SetWindowPos.argtypes = (wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,
                                               ctypes.c_int,ctypes.c_int,wintypes.UINT)
        backend.user32.SetWindowPos.restype = wintypes.BOOL

    def target(self, owner):
        backend = self.backend
        hwnd, pid, created = owner['hwnd'], owner['pid'], owner['created']
        if (not backend.exists(hwnd) or backend.pid(hwnd) != pid
                or backend.foreground() != hwnd or backend.process_exited(pid, created)):
            return None
        from gameframe.devices.windows import _physical_coordinates
        with _physical_coordinates(backend.user32):
            left, top, right, bottom = backend.gui.GetClientRect(hwnd)
            x, y = backend.gui.ClientToScreen(hwnd,(left,top))
            dpi = backend.user32.GetDpiForWindow(hwnd)
        return {'owner':dict(owner),'x':x,'y':y,'width':right-left,'height':bottom-top,'dpi':dpi}

    def place(self, widget, rect):
        from gameframe.devices.windows import _physical_coordinates
        with _physical_coordinates(self.backend.user32):
            if not self.backend.user32.SetWindowPos(int(widget.winId()), -1, *rect, 0x0010):
                raise ctypes.WinError()  # HWND_TOPMOST, SWP_NOACTIVATE


class PatchOverlay(QWidget):
    def __init__(self, *, geometry=None):
        super().__init__()
        self.geometry_source = geometry if geometry is not None else WindowsOverlayGeometry()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.owner_id = None
        self.target = None
        self.patch = None
        self.image = QImage()
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.refresh_target)

    def apply_event(self, event):
        if event['event'] == 'overlay-clear':
            if self.owner_id == event['owner_id']:
                self.clear()
            return
        target, patch = event['target'], event['patch']
        try:
            image = QImage.fromData(base64.b64decode(patch['png'],validate=True),'PNG')
        except Exception:
            self.clear()
            raise
        if image.isNull() or image.width()!=patch['width'] or image.height()!=patch['height']:
            self.clear()
            raise ValueError('Invalid overlay PNG dimensions')
        self.owner_id, self.target, self.patch, self.image = event['owner_id'],target,patch,image
        self.refresh_target()
        if self.target is not None:
            self.timer.start()

    def refresh_target(self):
        if self.target is None:
            return
        try:
            self._refresh_target()
        except Exception:
            self.clear()
            logging.getLogger(__name__).exception('Overlay target placement failed')

    def _refresh_target(self):
        current = self.geometry_source.target(self.target['owner'])
        if (current is None or current['width']!=self.target['width']
                or current['height']!=self.target['height']):
            self.clear()
            return
        patch = self.patch
        self.show()
        self.geometry_source.place(self,(current['x']+patch['x'],current['y']+patch['y'],
                                         patch['width'],patch['height']))
        self.update()

    def clear(self):
        self.timer.stop()
        self.hide()
        self.owner_id = self.target = self.patch = None
        self.image = QImage()

    def paintEvent(self,event):
        painter = QPainter(self)
        painter.drawImage(self.rect(),self.image)
