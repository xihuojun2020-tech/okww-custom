from ok import BrowserInteraction, PostMessageInteraction
from src.task.MouseResetTask import MouseResetTask


class WWOneTimeTask:

    def run(self):
        mouse_reset_task = self.executor.get_task_by_class(MouseResetTask)
        mouse_reset_task.run()
        if isinstance(self.executor.interaction, PostMessageInteraction):
            self.executor.interaction.activate()
        self.sleep(0.5)

    # ==================== 退登 / 屏幕操作（原序列切换任务，保留给每日任务/多账号任务用） ====================

    def _ensure_pc_login_screen(self):
        """确保 PC 端处于登录界面（切换下一个账号前调用）。

        每日任务正常结束后自动退登 PC 端，准备下一个账号。
        流程（用户实测校准）：
          等20s → ESC → 等10s → 点退出登录(0.040,0.942) → 识别「返回登录」点击
          → 等20s → 识别「登录」点击 → 等待下一个账号
        """
        self.log_info('每日任务完成，自动退登 PC 端准备下一个账号', notify=True)
        self.sleep(20)

        # ESC 退出当前界面
        try:
            self.send_key('esc')
            self.log_info('已发送 ESC 键')
        except Exception as e:
            self.log_error('发送 ESC 失败', e)
        self.sleep(10)

        # 点「退出登录」按钮（用户实测屏幕归一化坐标 0.040,0.942）
        import ctypes
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
        px, py = int(0.040 * sw), int(0.942 * sh)
        self._mouse_click(px, py)
        self.log_info(f'点击退出登录 ({px},{py})')
        self.sleep(3)

        # 识别「返回登录」字样并点击（OCR，找不到则提示）
        if not self._screen_tap_text('返回登录'):
            self.log_info('未识别到「返回登录」，继续流程')
        self.sleep(20)

        # 识别鸣潮界面「登录」字样并点击
        if not self._screen_tap_text('登录'):
            self.log_info('未识别到「登录」，继续流程')
        self.log_info('已退登，等待下一个账号登录', notify=True)

    def _screen_grab(self):
        """Windows 桌面全屏截图，返回 BGR ndarray。"""
        import ctypes
        from ctypes import wintypes
        import numpy as np
        import cv2
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        hdc = user32.GetDC(0)
        mdc = gdi32.CreateCompatibleDC(hdc)
        hbmp = gdi32.CreateCompatibleBitmap(hdc, sw, sh)
        gdi32.SelectObject(mdc, hbmp)
        gdi32.BitBlt(mdc, 0, 0, sw, sh, hdc, 0, 0, 0x00CC0020)  # SRCCOPY

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = sw
        bmi.biHeight = -sh  # top-down
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0
        buf = ctypes.create_string_buffer(sw * sh * 4)
        try:
            gdi32.GetDIBits(mdc, hbmp, 0, sh, buf, ctypes.byref(bmi), 0)
            img = np.frombuffer(buf, np.uint8).reshape(sh, sw, 4)
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        finally:
            # 无论成功失败都释放 GDI 句柄，防泄漏
            gdi32.DeleteObject(hbmp)
            gdi32.DeleteDC(mdc)
            user32.ReleaseDC(0, hdc)

    def _screen_find_text(self, text, threshold=0.4):
        """全屏 OCR 找文字，返回屏幕像素中心 (x,y)；未找到返回 None。"""
        frame = self._screen_grab()
        results = self.ocr_text(frame, threshold=threshold)
        text = text.strip()
        for t, x, y, w, h in results:
            if t.strip() == text:
                return int(x + w / 2), int(y + h / 2)
        best, best_diff = None, 10 ** 9
        for t, x, y, w, h in results:
            t = t.strip()
            if t and (text in t or t in text):
                diff = abs(len(t) - len(text))
                if diff < best_diff:
                    best_diff = diff
                    best = (int(x + w / 2), int(y + h / 2))
        return best

    def _mouse_click(self, px, py):
        """Windows 鼠标移动+左键点击（屏幕像素坐标）。"""
        import ctypes
        user32 = ctypes.windll.user32
        user32.SetCursorPos(int(px), int(py))
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
        self.sleep(0.2)

    def _screen_tap_text(self, text, fallback=None, threshold=0.4):
        """全屏 OCR 找文字 → 鼠标点击。找不到用 fallback 归一化屏幕坐标。"""
        pos = self._screen_find_text(text, threshold=threshold)
        if pos:
            self._mouse_click(pos[0], pos[1])
            self.log_info(f'屏幕 OCR 点击「{text}」于 {pos} (屏幕像素)')
            return True
        if fallback:
            import ctypes
            sw = ctypes.windll.user32.GetSystemMetrics(0)
            sh = ctypes.windll.user32.GetSystemMetrics(1)
            px, py = int(fallback[0] * sw), int(fallback[1] * sh)
            self._mouse_click(px, py)
            self.log_info(f'屏幕 OCR 未找到「{text}」，兜底点击 ({px},{py})')
            return True
        self.log_info(f'屏幕 OCR 未找到「{text}」且无兜底')
        return False
