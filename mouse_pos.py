# -*- coding: utf-8 -*-
"""鼠标坐标查看器：实时显示鼠标位置，用于标定 UI 元素坐标（如扫码按钮）。

用法（Windows）：
    .venv\\Scripts\\python.exe mouse_pos.py

操作：
    移动鼠标到目标位置（如【扫码】按钮中心）
    按 空格     记录当前坐标（像素 + 归一化，自动生成 fallback 配置片段到剪贴板）
    按 q / Esc  退出，所有记录打印到控制台

输出示例：
    记录: (960, 540) 归一化: (0.500, 0.500)
    fallback 片段: "fallback":[0.500, 0.500]

把 fallback 片段粘贴到 ADBSwitchTask.json 的「PC 端扫码步骤（高级）」对应步骤即可。
"""

import ctypes
import tkinter as tk

user32 = ctypes.windll.user32


def get_pos():
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


class MousePosApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("鼠标坐标查看器")
        self.root.attributes("-topmost", True)  # 置顶，方便边看边移动鼠标
        self.screen_w = user32.GetSystemMetrics(0)
        self.screen_h = user32.GetSystemMetrics(1)
        self.records = []

        tk.Label(self.root,
                 text=f"屏幕 {self.screen_w}x{self.screen_h}   空格=记录  q/Esc=退出",
                 font=("Microsoft YaHei", 9), fg="gray").pack(padx=10, pady=(8, 2))
        self.pos_label = tk.Label(self.root, text="", font=("Consolas", 18), fg="#1565C0")
        self.pos_label.pack(padx=10, pady=4)
        self.list_label = tk.Label(self.root, text="已记录:（空）", font=("Consolas", 10),
                                   justify="left", anchor="w")
        self.list_label.pack(padx=10, pady=(4, 8))

        self.root.bind("<space>", self.record)
        self.root.bind("q", self.quit)
        self.root.bind("Q", self.quit)
        self.root.bind("<Escape>", self.quit)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self._update()

    def _update(self):
        x, y = get_pos()
        nx, ny = x / self.screen_w, y / self.screen_h
        self.pos_label.config(text=f"({x}, {y})   归一化 (%.3f, %.3f)" % (nx, ny))
        self.root.after(100, self._update)

    def record(self, _evt=None):
        x, y = get_pos()
        nx, ny = x / self.screen_w, y / self.screen_h
        self.records.append((x, y, nx, ny))
        fb = '"fallback":[%.3f, %.3f]' % (nx, ny)
        print(f"记录: ({x}, {y})  归一化: (%.3f, %.3f)  →  {fb}" % (nx, ny))
        # 复制 fallback 片段到剪贴板
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(fb)
            tip = "（已复制到剪贴板）"
        except Exception:
            tip = ""
        lines = "已记录:\n" + "\n".join(
            f"({r[0]},{r[1]}) (%.3f,%.3f)  {fb}" % (r[2], r[3]) for r in self.records
        )
        self.list_label.config(text=lines + f"\n最新片段已复制{tip}")
        self.list_label.config(text=self.list_label.cget("text"))

    def quit(self, _evt=None):
        print("=" * 40)
        print("最终记录（像素 与 归一化）：")
        for i, (x, y, nx, ny) in enumerate(self.records, 1):
            print(f"  {i}. ({x}, {y})  (%.3f, %.3f)  fallback:[%.3f, %.3f]" % (nx, ny, nx, ny))
        self.root.destroy()


if __name__ == "__main__":
    MousePosApp().root.mainloop()
