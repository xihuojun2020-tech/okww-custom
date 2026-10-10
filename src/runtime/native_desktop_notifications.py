# SPDX-License-Identifier: AGPL-3.0-or-later
"""QQ/WeChat notifications dispatched only at the existing session owner boundary."""
from concurrent.futures import Future
from contextlib import nullcontext
from dataclasses import dataclass
from queue import Empty, Queue
import threading
import time


@dataclass(frozen=True)
class WindowIdentity:
    hwnd: int
    pid: int
    created: float


class DesktopFailure(RuntimeError):
    pass


class WindowsMessengerBackend:
    """Independently implemented Win32 boundary; no legacy framework imports."""
    def __init__(self):
        import ctypes
        import psutil
        import win32api
        import win32gui
        import win32process
        import win32ui
        self.psutil, self.gui, self.api = psutil, win32gui, win32api
        self.process, self.ui = win32process, win32ui
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.user32.GetDpiForWindow.argtypes = (ctypes.c_void_p,)
        self.user32.GetDpiForWindow.restype = ctypes.c_uint
        self.user32.PrintWindow.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint)
        self.user32.PrintWindow.restype = ctypes.c_int
        self.user32.SetThreadDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
        self.user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p

    def identity(self, hwnd):
        pid = self.process.GetWindowThreadProcessId(hwnd)[1]
        return WindowIdentity(hwnd, pid, self.psutil.Process(pid).create_time())

    def valid(self, identity):
        if not self.gui.IsWindow(identity.hwnd): return False
        if self.process.GetWindowThreadProcessId(identity.hwnd)[1] != identity.pid: return False
        try: return self.psutil.Process(identity.pid).create_time() == identity.created
        except self.psutil.NoSuchProcess: return False

    def _trusted(self, identity):
        if not self.valid(identity): raise DesktopFailure('target-identity-changed')

    def foreground(self):
        hwnd = self.gui.GetForegroundWindow()
        return self.identity(hwnd) if hwnd else None

    def activate(self, identity):
        self._trusted(identity)
        self.gui.SetForegroundWindow(identity.hwnd)
        if self.gui.GetForegroundWindow() != identity.hwnd:
            raise DesktopFailure('foreground-not-acquired')

    def find(self, route):
        names = {'qq-desktop': {'qq.exe'}, 'wechat-desktop': {'wechat.exe', 'weixin.exe'}}[route]
        candidates = []
        def collect(hwnd, _):
            if not self.gui.IsWindowVisible(hwnd): return True
            try:
                identity = self.identity(hwnd)
                if self.psutil.Process(identity.pid).name().lower() not in names: return True
                width, height, _ = self.geometry(identity)
                if width >= 400 and height >= 300: candidates.append((width*height, identity))
            except self.psutil.NoSuchProcess:
                pass  # A disappeared enumeration candidate is not a selected target.
            return True
        self.gui.EnumWindows(collect, None)
        if not candidates: raise DesktopFailure('messenger-window-not-found')
        return max(candidates, key=lambda item: item[0])[1]

    def windows(self, identity):
        self._trusted(identity)
        result = [identity]
        def collect(hwnd, _):
            if (hwnd != identity.hwnd and self.gui.IsWindowVisible(hwnd)
                    and self.process.GetWindowThreadProcessId(hwnd)[1] == identity.pid):
                result.append(WindowIdentity(hwnd, identity.pid, identity.created))
            return True
        self.gui.EnumWindows(collect, None)
        return result

    def geometry(self, identity):
        from gameframe.devices.windows import _physical_coordinates
        self._trusted(identity)
        with _physical_coordinates(self.user32):
            left, top, right, bottom = self.gui.GetClientRect(identity.hwnd)
        dpi = self.user32.GetDpiForWindow(identity.hwnd)
        if not dpi: raise DesktopFailure('window-dpi-unavailable')
        return right-left, bottom-top, dpi/96

    def capture(self, identity):
        from gameframe.devices.windows import _physical_coordinates
        with _physical_coordinates(self.user32): return self._capture(identity)

    def _capture(self, identity):
        import numpy as np
        width, height, _ = self.geometry(identity)
        if width <= 0 or height <= 0: raise DesktopFailure('messenger-client-unavailable')
        handle = self.gui.GetDC(identity.hwnd)
        source = self.ui.CreateDCFromHandle(handle)
        memory, bitmap = source.CreateCompatibleDC(), self.ui.CreateBitmap()
        try:
            bitmap.CreateCompatibleBitmap(source, width, height)
            memory.SelectObject(bitmap)
            if not self.user32.PrintWindow(identity.hwnd, memory.GetSafeHdc(), 3):
                raise DesktopFailure('messenger-capture-failed')
            return np.frombuffer(bitmap.GetBitmapBits(True), dtype=np.uint8).reshape(height, width, 4)[:, :, :3].copy()
        finally:
            memory.DeleteDC()
            source.DeleteDC()
            self.gui.ReleaseDC(identity.hwnd, handle)
            self.gui.DeleteObject(bitmap.GetHandle())

    def menus(self, identity):
        result = self.windows(identity)
        def child(hwnd, _):
            if self.gui.GetClassName(hwnd) == 'Chrome_RenderWidgetHostHWND':
                result.insert(0, WindowIdentity(hwnd, identity.pid, identity.created))
            return True
        self.gui.EnumChildWindows(identity.hwnd, child, None)
        return result

    def _message(self, identity, message, wparam, lparam):
        self._trusted(identity)  # Validate only at the actual OS input boundary.
        return self.gui.SendMessageTimeout(identity.hwnd, message, wparam, lparam, 2, 1000)

    def _target(self, identity, point=None):
        renderers = []
        def child(hwnd, _):
            if self.gui.GetClassName(hwnd) == 'Chrome_RenderWidgetHostHWND': renderers.append(hwnd)
            return True
        self.gui.EnumChildWindows(identity.hwnd, child, None)
        if not renderers: return identity, point
        target = WindowIdentity(renderers[0], identity.pid, identity.created)
        if point is not None:
            screen = self.gui.ClientToScreen(identity.hwnd, tuple(map(int, point)))
            point = self.gui.ScreenToClient(target.hwnd, screen)
        return target, point

    def click(self, identity, point, right=False):
        identity, point = self._target(identity, point)
        packed = self.api.MAKELONG(int(point[0]), int(point[1]))
        down, up, flag = (0x204, 0x205, 2) if right else (0x201, 0x202, 1)
        self._message(identity, 0x200, 0, packed)
        try: self._message(identity, down, flag, packed)
        finally: self._message(identity, up, 0, packed)

    def key(self, identity, key):
        code = self.api.MapVirtualKey(key, 0) << 16 | 1
        try: self._message(identity, 0x100, key, code)
        finally: self._message(identity, 0x101, key, code | 0xC0000000)

    def clear_search(self, identity):
        identity, _ = self._target(identity)
        code = self.api.MapVirtualKey(17, 0) << 16 | 1
        try:
            self._message(identity, 0x100, 17, code)
            self.key(identity, ord('A'))
        finally: self._message(identity, 0x101, 17, code | 0xC0000000)
        self.key(identity, 8)

    def type_text(self, identity, text):
        import struct
        identity, _ = self._target(identity)
        encoded = text.encode('utf-16-le')
        for code, in struct.iter_unpack('<H', encoded): self._message(identity, 0x102, code, 1)


class MessengerSender:
    def __init__(self, backend, ocr_engine, *, stop, pause, clipboard=None,
                 clock=time.monotonic, wait=None):
        self.backend, self.ocr = backend, ocr_engine
        self.stop, self.pause, self.clipboard = stop, pause, clipboard
        self.clock, self.wait = clock, wait or stop.wait
        self.target = None
        self.submitted = 0

    def _check(self):
        if self.stop.is_set(): raise DesktopFailure('stopped')
        if self.pause.is_set(): raise DesktopFailure('paused')

    def _boxes(self, identity):
        self._check()
        raw = self.ocr.ocr(self.backend.capture(identity))
        boxes = []
        for points, (text, confidence) in (raw[0] if raw else []):
            if confidence < .1: continue
            xs, ys = zip(*points)
            boxes.append((str(text).strip(), min(xs), min(ys), max(xs), max(ys)))
        return boxes

    @staticmethod
    def _point(box): return (box[1]+box[3])/2, (box[2]+box[4])/2

    def _wait(self, observation, failure):
        deadline = self.clock() + 8
        while True:
            self._check()
            result = observation()
            if result is not None: return result
            if self.clock() >= deadline: raise DesktopFailure(failure)
            self.wait(.2)

    def _match(self, identity, names, region):
        for box in self._boxes(identity):
            x, y = self._point(box)
            if box[0].casefold() in names and region[0] <= x <= region[2] and region[1] <= y <= region[3]:
                return self._point(box)

    def send(self, route, nickname, title, message, png_images=()):
        if route not in ('qq-desktop', 'wechat-desktop'): raise ValueError('Unknown desktop route')
        if not isinstance(nickname, str) or not nickname.strip(): raise DesktopFailure('contact-not-configured')
        self._check()
        self.target = None
        self.submitted = 0
        identity = self.backend.find(route)
        self.target = identity
        self.backend.activate(identity)
        width, height, scale = self.backend.geometry(identity)
        panel = min(width, (377 if route == 'qq-desktop' else 295)*scale)
        contact_area = (55*scale, 75*scale, panel, height)
        send_area = (max(panel, width-260*scale), height-150*scale, width, height)
        header_area = (panel, 0, width, 140*scale)
        wanted = {nickname.strip().casefold()}
        contact = self._match(identity, wanted, contact_area)
        if contact is not None:
            self.backend.click(identity, contact)
        elif self._match(identity, wanted, header_area) is None:
            search_area = (55*scale, 0, panel, 120*scale)
            search = self._match(identity, {'search', '搜索', '搜尋'}, search_area)
            if search is None: raise DesktopFailure('search-field-not-verified')
            self.backend.click(identity, search)
            self.backend.clear_search(identity)
            self.backend.type_text(identity, nickname.strip())
            def find_contact():
                for window in self.backend.windows(identity):
                    if window == identity:
                        point = self._match(window, wanted, contact_area)
                    else:
                        boxes = self._boxes(window)
                        sections = sorted(boxes, key=lambda box: box[2])
                        allowed = False
                        point = None
                        for box in sections:
                            text = box[0].casefold()
                            if text in {'contacts','contact','联系人','聯絡人','features','功能'}: allowed = True
                            elif text in {'chat history','聊天记录','聊天記錄','group chats','群聊','more','更多',
                                           'internet search results','网络搜索结果','網路搜尋結果'}: allowed = False
                            elif allowed and text in wanted:
                                point = self._point(box)
                                break
                    if point is not None: return window, point
            window, contact = self._wait(find_contact, 'contact-not-verified')
            self.backend.click(window, contact)
        self._wait(lambda: self._match(identity, wanted, header_area), 'conversation-not-verified')
        send_point = self._wait(lambda: self._match(identity, {'send','发送','發送'}, send_area), 'send-button-not-verified')
        composer = (max(panel, send_point[0]-80*scale), send_point[1]-45*scale)
        draft_area = (panel, height-180*scale, width, send_point[1]-20*scale)
        for box in self._boxes(identity):
            x, y = self._point(box)
            if (draft_area[0] <= x <= draft_area[2] and draft_area[1] <= y <= draft_area[3]
                    and box[0].casefold() not in {'type a message', '输入消息', '輸入訊息'}):
                raise DesktopFailure('composer-has-unsent-text')
        outgoing_area = (panel, 140*scale, width, max(140*scale, height-200*scale))
        def outgoing():
            return [box for box in self._boxes(identity) if self._point(box)[0] >= width*.55
                    and outgoing_area[1] <= self._point(box)[1] <= outgoing_area[3]]
        text = f'{title}\n{message}' if title else message
        normalize = lambda value: ''.join(value.split()).casefold()
        needle = normalize(text)
        def occurrences():
            return normalize(''.join(box[0] for box in sorted(outgoing(), key=lambda box:(box[2],box[1])))).count(needle)
        images = tuple(png_images)
        if images and self.clipboard is None: raise DesktopFailure('clipboard-owner-not-configured')
        submitted = 0
        with self.clipboard.preserve() if images else nullcontext() as clipboard:
            if text:
                before = occurrences()
                self._check()
                if self._match(identity, wanted, header_area) is None:
                    raise DesktopFailure('conversation-changed')
                self.backend.click(identity, composer)
                self.backend.type_text(identity, text)
                self._check()
                if self._match(identity, wanted, header_area) is None:
                    raise DesktopFailure('conversation-changed')
                self.backend.click(identity, send_point)
                submitted += 1
                self.submitted = submitted
                self._wait(lambda: True if occurrences() > before else None, 'outgoing-text-not-verified')
            for image in images:
                self._check()
                if self._match(identity, wanted, header_area) is None:
                    raise DesktopFailure('conversation-changed')
                before = self.backend.capture(identity)
                clipboard.set_png(image)
                self.backend.click(identity, composer, right=True)
                def paste_menu():
                    for window in self.backend.menus(identity):
                        width2, height2, _ = self.backend.geometry(window)
                        point = self._match(window, {'paste','粘贴','貼上'}, (0,0,width2,height2))
                        if point is not None: return window, point
                menu, paste = self._wait(paste_menu, 'paste-menu-not-verified')
                self.backend.click(menu, paste)
                self._check()
                if self._match(identity, wanted, header_area) is None:
                    raise DesktopFailure('conversation-changed')
                self.backend.click(identity, send_point)
                submitted += 1
                self.submitted = submitted
                def image_changed():
                    import cv2
                    import numpy as np
                    current = self.backend.capture(identity)
                    x, y, right, bottom = map(int, outgoing_area)
                    old = before[y:bottom,x:right]
                    new = current[y:bottom,x:right]
                    template = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
                    if template is None: raise DesktopFailure('image-png-invalid')
                    def matches(frame):
                        best = 0
                        max_scale = min(1, frame.shape[1]/template.shape[1], frame.shape[0]/template.shape[0])
                        for factor in np.linspace(max_scale/5, max_scale, 16):
                            width3, height3 = round(template.shape[1]*factor), round(template.shape[0]*factor)
                            if min(width3,height3) < 16: continue
                            resized = cv2.resize(template, (width3,height3))
                            scores = cv2.matchTemplate(frame, resized, cv2.TM_SQDIFF_NORMED)
                            count, _ = cv2.connectedComponents((scores < .025).astype(np.uint8))
                            best = max(best, count-1)
                        return best
                    return True if old.shape == new.shape and matches(new) > matches(old) else None
                self._wait(image_changed, 'outgoing-image-not-verified')
        return {'route': route, 'status': 'delivered', 'submitted_messages': submitted}


class OwnerDesktopNotifications:
    def __init__(self, context, sender, config, *, owner_check, sender_factory=None,
                 desktop_available=True):
        owner_check()
        self.context, self.sender, self.owner_check = context, sender, owner_check
        self.config = config
        self.sender_factory = sender_factory
        self.desktop_available = desktop_available
        self.thread = threading.get_ident()
        self.queue = Queue()
        self.closed = False
        self.lock = threading.Lock()

    def submit(self, title, message, png_images=()):
        futures = []
        images = tuple(png_images)
        with self.lock:
            if self.closed: raise RuntimeError('Desktop notification owner is closed')
            for route, enabled, contact in (
                ('qq-desktop', 'QQ Desktop Notification (Not Reliable)', 'QQ Desktop Nickname'),
                ('wechat-desktop', 'WeChat Desktop Notification (Not Reliable)', 'WeChat Desktop Nickname')):
                if self.config.get(enabled) is True:
                    future = Future()
                    self.queue.put((future, route, self.config.get(contact), title, message, images))
                    futures.append(future)
        return tuple(futures)

    @property
    def pending(self): return not self.queue.empty()

    def checkpoint(self):
        if not self.queue.empty():
            from src.runtime.native_combat_executor import SessionPreempted
            raise SessionPreempted('Desktop notification yielded to the session input owner')

    def drain_one(self):
        if threading.get_ident() != self.thread: raise RuntimeError('Desktop notification requires owner thread')
        self.owner_check()
        if self.context.stop.is_set() or self.context.pause.is_set(): return False
        try: future, route, nickname, title, message, images = self.queue.get_nowait()
        except Empty: return False
        if not future.set_running_or_notify_cancel(): return True
        enabled = ('QQ Desktop Notification (Not Reliable)' if route == 'qq-desktop'
                   else 'WeChat Desktop Notification (Not Reliable)')
        if self.config.get(enabled) is not True:
            future.set_result({'route': route, 'status': 'skipped', 'reason': 'route-disabled'})
            return True
        if not self.desktop_available:
            future.set_result({'route': route, 'status': 'unavailable',
                              'failure': 'windows-desktop-device-required', 'submitted_messages': 0})
            return True
        backend = None
        previous = target = None
        result = None
        try:
            if self.sender is None: self.sender = self.sender_factory()
            self.sender.target = None
            self.sender.submitted = 0
            backend = self.sender.backend
            previous = backend.foreground()
            self.context.device.release_all()
            result = self.sender.send(route, nickname, title, message, images)
        except DesktopFailure as error:
            result = {'route': route, 'status': 'failed', 'failure': str(error)}
        except Exception:
            result = {'route': route, 'status': 'failed', 'failure': 'desktop-operation'}
        finally:
            try:
                self.context.device.release_all()
                target = self.sender.target if self.sender is not None else None
                if previous is not None and backend.valid(previous):
                    current = backend.foreground()
                    if target is not None and current == target: backend.activate(previous)
            except Exception:
                result = {'route': route, 'status': 'failed', 'failure': 'owner-restoration',
                          'submitted_messages': self.sender.submitted if self.sender is not None else 0}
            result['submitted_messages'] = self.sender.submitted if self.sender is not None else 0
            future.set_result(result)
        return True

    def close(self):
        with self.lock:
            self.closed = True
            while True:
                try: future, *_ = self.queue.get_nowait()
                except Empty: break
                future.cancel()


def create_owner_desktop_notifications(context, ocr_engine, config):
    """Bind the live owner now; initialize Win32/clipboard only on an enabled send."""
    def sender_factory():
        from src.runtime.native_desktop_clipboard import OleClipboardAPI, PreservedClipboard
        return MessengerSender(WindowsMessengerBackend(), ocr_engine,
                               stop=context.stop, pause=context.pause,
                               clipboard=PreservedClipboard(OleClipboardAPI()))
    return OwnerDesktopNotifications(context, None, config,
                                     owner_check=context.assert_input_owner,
                                     sender_factory=sender_factory,
                                     desktop_available='desktop-handoff' in context.device.capabilities)
