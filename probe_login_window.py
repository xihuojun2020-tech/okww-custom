# -*- coding: utf-8 -*-
"""运行端探针：确认「登录账号下拉框是否在独立窗口」的假设。

用法（运行端，游戏退登后停在登录界面/或卡死状态时执行）：
    runtime\\python\\python.exe probe_login_window.py
输出：
    1) client-win64-shipping.exe 的所有顶层窗口（类名/标题/可见性/矩形）
    2) 每个可见窗口的截图（保存到 probe_login_out/ 目录）
    3) 若 okww 在运行，尝试读取其主窗口与 top_hwnd 的匹配情况（仅打印，不改动）
"""
import ctypes
import os
import sys

import win32gui
import win32ui
import win32con

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe_login_out")
os.makedirs(OUT_DIR, exist_ok=True)

EXE_NAME = "Client-Win64-Shipping.exe"
TOP_CLASSES = ["CNativeLoginDlg", "CLoginDlg_P_", "CefBrowserWindow",
               "Chrome_RenderWidgetHostHWND", "UnrealWindow"]


def get_exe_by_hwnd(hwnd):
    try:
        import win32process
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        import psutil
        p = psutil.Process(pid)
        return p.name(), p.exe()
    except Exception:
        return None, None


def capture_window(hwnd, path):
    """BitBlt 捕获指定顶层窗口为 PNG。"""
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        w = right - left
        h = bottom - top
        if w <= 0 or h <= 0:
            return False
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)
        save_dc.BitBlt((0, 0), (w, h), mfc_dc, (0, 0), win32con.SRCCOPY)
        bmp.SaveBitmapFile(save_dc, path)
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        return True
    except Exception as e:
        print(f"   [capture fail] hwnd={hwnd} err={e}")
        return False


def enum_windows():
    found = []
    def cb(hwnd, _):
        try:
            exe, _ = get_exe_by_hwnd(hwnd)
            if exe and exe.lower() == EXE_NAME.lower():
                cls = win32gui.GetClassName(hwnd)
                title = win32gui.GetWindowText(hwnd)
                visible = win32gui.IsWindowVisible(hwnd)
                rect = win32gui.GetWindowRect(hwnd)
                found.append((hwnd, cls, title, visible, rect))
        except Exception:
            pass
        return True
    win32gui.EnumWindows(cb, None)
    return found


def main():
    print("=" * 60)
    print("运行端探针：登录窗口假设验证")
    print(f"目标进程: {EXE_NAME}")
    print("=" * 60)
    wins = enum_windows()
    print(f"\n找到 {len(wins)} 个 {EXE_NAME} 顶层窗口：")
    for hwnd, cls, title, visible, rect in wins:
        flag = "可见" if visible else "不可见"
        print(f"  hwnd={hwnd} 类={cls!r} 标题={title!r} [{flag}] rect={rect}")
        if visible and cls not in ("ComboBox", "ComboLBox", "Button", "Static"):
            path = os.path.join(OUT_DIR, f"hwnd_{hwnd}_{cls.replace('/', '_')}.png")
            ok = capture_window(hwnd, path)
            if ok:
                print(f"    -> 截图已保存: {path}")
    print("\n判断标准：")
    print("  - 若登录账号下拉框（掩码 199****0005 / 登录按钮）出现在某个『非 UnrealWindow』窗口的截图里")
    print("    -> 假设成立：登录 UI 在独立窗口，主窗口捕获永远看不到它")
    print("  - 若 UnrealWindow 自己的截图里就有登录选项 -> 假设不成立，另找原因")
    print(f"\n输出目录: {OUT_DIR}")
    print("请把上面的窗口列表 + 截图发回开发端。")


if __name__ == "__main__":
    main()
