"""Minimal click-through task status overlay."""

import ctypes
import html
import time
from dataclasses import replace

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from ok.gui.Communicate import communicate
from src.task_status import choose_status_position, read_task_status


WDA_EXCLUDEFROMCAPTURE = 0x11


def exclude_window_from_capture(hwnd, user32=None):
    try:
        user32 = user32 or ctypes.windll.user32
        return bool(user32.SetWindowDisplayAffinity(int(hwnd), WDA_EXCLUDEFROMCAPTURE))
    except (AttributeError, OSError, TypeError, ValueError):
        return False


class TaskStatusWindow(QWidget):
    def __init__(self, executor):
        super().__init__(None)
        self.executor = executor
        self.last_task = None
        self.paused = bool(getattr(executor, "paused", False))
        self.warning_text = ""
        self.warning_seen_at = 0.0
        self.capture_excluded = False
        self.capture_exclusion_checked = False
        self._running_tasks = set()
        self._terminal_message = ""

        self.setFixedSize(340, 110)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.WindowTransparentForInput |
            Qt.WindowDoesNotAcceptFocus
        )
        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.NoTextInteraction)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.addWidget(self.label)
        self.setStyleSheet(
            "QWidget { background: rgba(0, 0, 0, 165); border-radius: 8px; }"
            "QLabel { background: transparent; color: white; font-size: 13px; }"
        )

        communicate.task.connect(self.on_task)
        communicate.task_done.connect(self.on_task_done)
        communicate.executor_paused.connect(self.on_paused)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    def on_task(self, task):
        if task is not None:
            if task is not self.last_task:
                self._terminal_message = ""
            if getattr(task, "running", False):
                self._running_tasks.add(id(task))
                self._terminal_message = ""
                self.warning_text = ""
                self.warning_seen_at = 0.0
            elif task is self.last_task and id(task) in self._running_tasks and not self._terminal_message:
                self._terminal_message = "用户停止任务"
            self.last_task = task
        self.refresh()

    def on_task_done(self, task):
        if task is not None:
            self.last_task = task
            self._terminal_message = "任务已完成"
        self.refresh()

    def on_paused(self, paused):
        self.paused = bool(paused)
        self.refresh()

    @staticmethod
    def _elapsed_text(seconds):
        hours, remainder = divmod(max(0, int(seconds)), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _game_rect(self):
        manager = getattr(self.executor, "device_manager", None)
        hwnd_window = getattr(manager, "hwnd_window", None)
        if hwnd_window is None or not getattr(hwnd_window, "exists", False):
            return None
        origin = hwnd_window.get_capture_origin()
        return int(origin[0]), int(origin[1]), int(hwnd_window.width), int(hwnd_window.height)

    def _place_safely(self):
        screens = QApplication.screens()
        areas = []
        for screen in screens:
            rect = screen.availableGeometry()
            areas.append((rect.x(), rect.y(), rect.width(), rect.height()))
        game_rect = self._game_rect()
        if not areas:
            return False
        if game_rect is None:
            ax, ay, aw, _unused_height = areas[0]
            self.move(ax + aw - self.width() - 12, ay + 12)
            return True
        position = choose_status_position(areas, game_rect, (self.width(), self.height()))
        if position is not None:
            self.move(*position)
            return True
        if self.capture_exclusion_checked and self.capture_excluded:
            ax, ay, aw, _unused_height = areas[0]
            self.move(ax + aw - self.width() - 12, ay + 12)
            return True
        return False

    def refresh(self):
        task = getattr(self.executor, "current_task", None) or self.last_task
        if task is None:
            self.hide()
            return
        snapshot = read_task_status(task, paused=self.paused)
        if self._terminal_message and snapshot.level == "running":
            snapshot = replace(snapshot, message=self._terminal_message)
        if snapshot.level == "warning":
            if snapshot.message != self.warning_text:
                self.warning_text = snapshot.message
                self.warning_seen_at = time.monotonic()
            if time.monotonic() - self.warning_seen_at > 10:
                snapshot = replace(snapshot, level="running", message=snapshot.detail)
        color = {
            "error": "#ff6b6b",
            "warning": "#ffd166",
            "paused": "#b8b8b8",
        }.get(snapshot.level, "#ffffff")
        detail = snapshot.message or snapshot.detail or "正在运行"
        completed = f" · 已完成 {snapshot.completed_count} 个账号" if snapshot.completed_count else ""
        lines = (
            f"账号：{html.escape(snapshot.account)}",
            f"阶段：{html.escape(snapshot.stage)}",
            f"详情：{html.escape(detail)}",
            f"已运行：{self._elapsed_text(snapshot.elapsed_seconds)}{completed}",
        )
        self.label.setStyleSheet(f"color: {color};")
        self.label.setText("\n".join(lines))

        # Create the native HWND and request exclusion before the first show.
        if not self.capture_exclusion_checked:
            self.capture_excluded = exclude_window_from_capture(int(self.winId()))
            self.capture_exclusion_checked = True
        if not self._place_safely():
            self.hide()
            return
        if not self.isVisible():
            self.show()

    def shutdown(self):
        self.timer.stop()
        self.hide()
        self.close()
