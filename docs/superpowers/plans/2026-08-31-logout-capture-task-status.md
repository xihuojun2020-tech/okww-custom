# Logout Capture and Task Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PC logout observation prefer a task-scoped foreground desktop capture while showing a minimal always-on-top status window with the current account, stage, detail, elapsed time, warnings, and errors.

**Architecture:** Keep global WGC and PostMessage configuration untouched. A task-scoped `LogoutCaptureSession` supplies explicit main-window frames and origins to the existing logout state machine, while native login dialogs retain their HWND BitBlt path. A project-owned status model writes three structured fields into the top-level task `info`, and a small PySide6 tool window polls those fields without receiving focus or entering capture.

**Tech Stack:** Python 3, ok-script task APIs, PySide6, pywin32, NumPy, OpenCV, Windows ForegroundBitBlt, Windows `SetWindowDisplayAffinity`, unittest.

**Spec:** `docs/superpowers/specs/2026-08-31-logout-capture-task-status-design.md`

## Global Constraints

- Work only in `E:\AI work\ok-wuthering-waves-master` with remote `https://github.com/xihuojun2020-tech/okww-custom.git`.
- Verify `master`, `origin/master`, and annotated tag `v1.21.00` resolve to `d4ffe04a4b530653aed516f1743fcd6b3492ef01` before changing code.
- Preserve and never stage the existing Android changes in `src/android/nemu.py`, `src/android/preflight.py`, `android/agent-app/`, and the 2026-08-26/27 Android plan/spec files.
- Never use `git add .`; stage only the exact files listed by each task.
- Use `.\.venv\Scripts\python.exe` for every Python command.
- Do not start, focus, capture, click, type into, log out of, or otherwise operate the real game during validation.
- Do not call `DeviceManager.set_capture()` or persistently change the selected capture backend.
- Do not change global `interaction: PostMessage`; PC login mouse input remains verified SendInput.
- Do not modify installed files under `.venv\Lib\site-packages`. Project framework customizations belong under `custom_ok\ok`.
- No new third-party dependencies.
- Publish as medium release `1.22.00`; push `master` and annotated tag `v1.22.00` only after all verification passes.

---

## Preflight: Confirm the Published Backup and Dirty-File Boundary

- [ ] **Step 1: Inspect the exact repository and current dirty files**

Run each command separately from `E:\AI work\ok-wuthering-waves-master`:

```powershell
git remote -v
git branch --show-current
git status --short
```

Expected:

- remote `origin` is `https://github.com/xihuojun2020-tech/okww-custom.git`;
- branch is `master`;
- only the known Android files/directories are dirty before the spec and plan created for this feature.

- [ ] **Step 2: Refresh remote references without changing the worktree**

```powershell
git fetch origin --prune --tags
```

Expected: exit code 0.

- [ ] **Step 3: Verify the backup commit and tag**

```powershell
git rev-parse HEAD
git rev-parse origin/master
git rev-parse "v1.21.00^{}"
```

Expected from all three commands:

```text
d4ffe04a4b530653aed516f1743fcd6b3492ef01
```

Stop implementation if any value differs. Do not merge, reset, stash, or overwrite the user's dirty Android work.

---

### Task 1: Open the 1.22.00 Release Boundary

**Files:**
- Modify: `config.py:21`
- Modify: `custom_ok/ok/gui/about/AboutTab.py:49`
- Modify: `更新日志.md:5`
- Add: `docs/superpowers/specs/2026-08-31-logout-capture-task-status-design.md`
- Add: `docs/superpowers/plans/2026-08-31-logout-capture-task-status.md`

**Interfaces:**
- Consumes: current published version `1.21.00`.
- Produces: product version `1.22.00` and release text that describes both approved features before code commits begin.

- [ ] **Step 1: Update the fixed-width version**

Change:

```python
version = "1.21.00"
```

to:

```python
version = "1.22.00"
```

- [ ] **Step 2: Add the About-page first release line**

Insert before the existing V1.21.00 line:

```python
'V1.22.00：退登状态机优先使用任务级前台桌面捕获并保留 WGC 后备；新增轻量置顶任务状态窗，显示当前账号、阶段、详情、耗时、告警和错误，独立登录窗口继续使用各自 HWND BitBlt。\n'
```

- [ ] **Step 3: Add the changelog entry**

Insert immediately above `## 1.21.00`:

```markdown
## 1.22.00（退登可靠截图与任务状态窗）

- 多账号退登开始后使用任务级 ForegroundBitBlt 观察主窗口；空帧、纯色帧或前台校验失败时回退 WGC，不修改全局捕获设置。
- 独立登录窗口、ComboBox 和 ComboLBox 保持各自 HWND BitBlt 与实时客户区坐标。
- 新增轻量透明置顶状态窗，显示当前账号、阶段、详情、运行时间以及最新告警或错误；窗口点击穿透且优先放置在游戏捕获区域之外。
- 自动验证仅使用伪窗口、伪帧和 Qt 离屏测试，不启动或操作游戏。
```

- [ ] **Step 4: Verify version text is synchronized**

```powershell
rg -n "1\.22\.00|V1\.22\.00" config.py custom_ok/ok/gui/about/AboutTab.py 更新日志.md
```

Expected: one config version, one About line, and one changelog heading.

- [ ] **Step 5: Commit only release metadata and planning documents**

```powershell
git add -- config.py custom_ok/ok/gui/about/AboutTab.py 更新日志.md docs/superpowers/specs/2026-08-31-logout-capture-task-status-design.md docs/superpowers/plans/2026-08-31-logout-capture-task-status.md
git diff --cached --name-only
git commit -m "docs: open 1.22.00 capture status release"
```

Expected staged file list contains exactly the five paths above and no Android path.

---

### Task 2: Add the Shared Minimal Task-Status Model

**Files:**
- Create: `src/task_status.py`
- Create: `tests/TestTaskStatus.py`
- Modify: `run_tests.ps1: unit group`

**Interfaces:**
- Consumes: any ok-script task with `executor.current_task`, `info`, `info_set()`, `name`, and `start_time`.
- Produces:
  - `publish_task_status(task, *, account=None, stage=None, detail=None) -> None`
  - `read_task_status(task, *, paused=False, now=None) -> TaskStatusSnapshot`
  - `choose_status_position(work_areas, game_rect, status_size, gap=12) -> tuple[int, int] | None`
  - constants `STATUS_ACCOUNT`, `STATUS_STAGE`, and `STATUS_DETAIL`.

- [ ] **Step 1: Write failing status publication and priority tests**

Create `tests/TestTaskStatus.py` with fakes that assert:

```python
import unittest

from src.task_status import (
    STATUS_ACCOUNT,
    STATUS_DETAIL,
    STATUS_STAGE,
    choose_status_position,
    publish_task_status,
    read_task_status,
)


class FakeTask:
    def __init__(self, name="Multi Account Daily", start_time=100.0):
        self.name = name
        self.start_time = start_time
        self.info = {}
        self.executor = type("Executor", (), {"current_task": self})()

    def info_set(self, key, value):
        self.info[key] = value

    def tr(self, value):
        return {"Error": "错误"}.get(value, value)


class TestTaskStatus(unittest.TestCase):
    def test_child_publication_writes_to_top_level_task(self):
        parent = FakeTask()
        child = FakeTask("Nightmare")
        child.executor.current_task = parent

        publish_task_status(
            child,
            account="A3",
            stage="刷梦魇巢穴",
            detail="落渊南丘残象聚落 · 正在战斗",
        )

        self.assertEqual("A3", parent.info[STATUS_ACCOUNT])
        self.assertEqual("刷梦魇巢穴", parent.info[STATUS_STAGE])
        self.assertEqual("落渊南丘残象聚落 · 正在战斗", parent.info[STATUS_DETAIL])
        self.assertEqual({}, child.info)

    def test_error_has_priority_over_warning_and_detail(self):
        task = FakeTask()
        task.info.update({
            STATUS_ACCOUNT: "A3",
            STATUS_STAGE: "账号切换",
            STATUS_DETAIL: "正在等待登录",
            "Warning": "WGC 暂无新帧",
            "Error": "无法唯一识别当前账号",
        })

        snapshot = read_task_status(task, now=160.0)

        self.assertEqual("error", snapshot.level)
        self.assertEqual("无法唯一识别当前账号", snapshot.message)
        self.assertEqual(60, snapshot.elapsed_seconds)

    def test_localized_executor_error_is_also_visible(self):
        task = FakeTask()
        task.info["错误"] = "子任务异常终止"

        snapshot = read_task_status(task, now=160.0)

        self.assertEqual("error", snapshot.level)
        self.assertEqual("子任务异常终止", snapshot.message)

    def test_position_prefers_a_non_game_monitor(self):
        work_areas = [(0, 0, 1920, 1040), (1920, 0, 1920, 1040)]
        position = choose_status_position(
            work_areas,
            game_rect=(0, 0, 1920, 1040),
            status_size=(340, 110),
        )
        self.assertEqual((3488, 12), position)

    def test_position_returns_none_when_no_safe_space_exists(self):
        position = choose_status_position(
            [(0, 0, 1920, 1040)],
            game_rect=(0, 0, 1920, 1040),
            status_size=(340, 110),
        )
        self.assertIsNone(position)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Register the new test file**

Add `TestTaskStatus.py` to the `unit` list in `run_tests.ps1`.

- [ ] **Step 3: Run the test and verify it fails**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestTaskStatus.py
```

Expected: FAIL because `src.task_status` does not exist.

- [ ] **Step 4: Implement the minimal shared model**

Create `src/task_status.py` with these public definitions:

```python
from dataclasses import dataclass
import time


STATUS_ACCOUNT = "Status Account"
STATUS_STAGE = "Status Stage"
STATUS_DETAIL = "Status Detail"


@dataclass(frozen=True)
class TaskStatusSnapshot:
    task_name: str
    account: str
    stage: str
    detail: str
    elapsed_seconds: int
    level: str
    message: str
    completed_count: int


def _status_owner(task):
    executor = getattr(task, "executor", None)
    return getattr(executor, "current_task", None) or task


def publish_task_status(task, *, account=None, stage=None, detail=None):
    try:
        owner = _status_owner(task)
        setter = getattr(owner, "info_set", None)
        values = (
            (STATUS_ACCOUNT, account),
            (STATUS_STAGE, stage),
            (STATUS_DETAIL, detail),
        )
        for key, value in values:
            if value is not None:
                if callable(setter):
                    setter(key, value)
                else:
                    owner.info[key] = value
    except Exception:
        return None
    return None


def _translated_info_value(task, info, key):
    keys = [key]
    translator = getattr(task, "tr", None)
    if callable(translator):
        try:
            keys.append(str(translator(key)))
        except Exception:
            pass
    for candidate in dict.fromkeys(keys):
        value = str(info.get(candidate) or "").strip()
        if value:
            return value
    return ""


def read_task_status(task, *, paused=False, now=None):
    now = time.time() if now is None else float(now)
    info = dict(getattr(task, "info", {}) or {})
    error = _translated_info_value(task, info, "Error")
    warning = _translated_info_value(task, info, "Warning")
    detail = str(info.get(STATUS_DETAIL) or info.get("Log") or "").strip()
    if error:
        level, message = "error", error
    elif warning:
        level, message = "warning", warning
    elif paused:
        level, message = "paused", "任务已暂停"
    else:
        level, message = "running", detail
    start_time = float(getattr(task, "start_time", 0) or 0)
    elapsed = max(0, int(now - start_time)) if start_time else 0
    completed = info.get("Completed") or []
    completed_count = len(completed) if isinstance(completed, (list, tuple, set)) else 0
    return TaskStatusSnapshot(
        task_name=str(getattr(task, "name", "") or ""),
        account=str(info.get(STATUS_ACCOUNT) or "-"),
        stage=str(info.get(STATUS_STAGE) or getattr(task, "name", "") or ""),
        detail=detail,
        elapsed_seconds=elapsed,
        level=level,
        message=message,
        completed_count=completed_count,
    )


def _intersects(left, right):
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    return not (
        lx + lw <= rx or rx + rw <= lx or
        ly + lh <= ry or ry + rh <= ly
    )


def choose_status_position(work_areas, game_rect, status_size, gap=12):
    width, height = status_size
    for area in work_areas:
        if not _intersects(area, game_rect):
            x, y, area_width, unused_height = area
            return x + area_width - width - gap, y + gap

    gx, gy, gw, gh = game_rect
    candidates = (
        (gx + gw + gap, gy + gap),
        (gx - width - gap, gy + gap),
        (gx + gw - width - gap, gy - height - gap),
        (gx + gw - width - gap, gy + gh + gap),
    )
    for px, py in candidates:
        status_rect = (px, py, width, height)
        if _intersects(status_rect, game_rect):
            continue
        for ax, ay, aw, ah in work_areas:
            if px >= ax and py >= ay and px + width <= ax + aw and py + height <= ay + ah:
                return px, py
    return None
```

- [ ] **Step 5: Run the status-model tests**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestTaskStatus.py
```

Expected: PASS.

- [ ] **Step 6: Commit the shared model**

```powershell
git add -- src/task_status.py tests/TestTaskStatus.py run_tests.ps1
git diff --cached --name-only
git commit -m "feat: add minimal task status model"
```

Expected: no Android paths staged.

---

### Task 3: Add the Transparent, Click-Through Status Window

**Files:**
- Create: `src/gui/TaskStatusWindow.py`
- Create: `tests/TestTaskStatusWindow.py`
- Modify: `custom_ok/ok/gui/MainWindow.py:70-84`
- Modify: `run_tests.ps1: ui group`

**Interfaces:**
- Consumes:
  - `read_task_status(task, paused=False, now=None)`
  - `choose_status_position(work_areas, game_rect, status_size)`
  - `executor.current_task` and `executor.paused`
  - `communicate.task`, `communicate.task_done`, and `communicate.executor_paused`.
- Produces:
  - `TaskStatusWindow(executor)`
  - `TaskStatusWindow.shutdown() -> None`
  - `exclude_window_from_capture(hwnd, user32=None) -> bool`.

- [ ] **Step 1: Write failing Qt window tests**

Create `tests/TestTaskStatusWindow.py`. Set `QT_QPA_PLATFORM=offscreen` before importing PySide6, create one QApplication, and assert:

```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.gui.TaskStatusWindow import TaskStatusWindow, exclude_window_from_capture
from src.task_status import publish_task_status


class FakeUser32:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def SetWindowDisplayAffinity(self, hwnd, affinity):
        self.calls.append((int(hwnd), int(affinity)))
        return self.result


class FakeTask:
    def __init__(self, name="Multi Account Daily", start_time=100.0):
        self.name = name
        self.start_time = start_time
        self.info = {}
        self.executor = None

    def info_set(self, key, value):
        self.info[key] = value

    def tr(self, value):
        return value


class FakeExecutor:
    def __init__(self, current_task=None):
        self.paused = False
        self.current_task = current_task
        self.device_manager = type("DeviceManager", (), {"hwnd_window": None})()
        if current_task is not None:
            current_task.executor = self


class TestTaskStatusWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_window_is_topmost_click_through_and_non_activating(self):
        window = TaskStatusWindow(FakeExecutor())
        flags = window.windowFlags()
        self.assertTrue(flags & Qt.WindowStaysOnTopHint)
        self.assertTrue(flags & Qt.WindowTransparentForInput)
        self.assertTrue(flags & Qt.WindowDoesNotAcceptFocus)
        window.shutdown()

    def test_capture_exclusion_uses_wda_excludefromcapture(self):
        user32 = FakeUser32(1)
        self.assertTrue(exclude_window_from_capture(123, user32=user32))
        self.assertEqual([(123, 0x11)], user32.calls)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Register the Qt test**

Add `TestTaskStatusWindow.py` to the `ui` group in `run_tests.ps1`.

- [ ] **Step 3: Run the test and verify it fails**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestTaskStatusWindow.py
```

Expected: FAIL because `src.gui.TaskStatusWindow` does not exist.

- [ ] **Step 4: Implement the fixed four-line tool window**

Create `src/gui/TaskStatusWindow.py` using:

```python
import ctypes
import html
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from ok.gui.Communicate import communicate
from src.task_status import choose_status_position, read_task_status


WDA_EXCLUDEFROMCAPTURE = 0x11


def exclude_window_from_capture(hwnd, user32=None):
    user32 = user32 or ctypes.windll.user32
    try:
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
            self.last_task = task
            self.warning_text = ""
            self.warning_seen_at = 0.0
        self.refresh()

    def on_task_done(self, task):
        if task is not None:
            self.last_task = task
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
            ax, ay, aw, unused_height = areas[0]
            self.move(ax + aw - self.width() - 12, ay + 12)
            return True
        position = choose_status_position(
            areas,
            game_rect,
            (self.width(), self.height()),
        )
        if position is not None:
            self.move(*position)
            return True
        if self.capture_exclusion_checked and self.capture_excluded:
            ax, ay, aw, unused_height = areas[0]
            self.move(ax + aw - self.width() - 12, ay + 12)
            return True
        return False

    def refresh(self):
        task = getattr(self.executor, "current_task", None) or self.last_task
        if task is None:
            self.hide()
            return
        snapshot = read_task_status(task, paused=self.paused)
        if snapshot.level == "warning":
            if snapshot.message != self.warning_text:
                self.warning_text = snapshot.message
                self.warning_seen_at = time.monotonic()
            if time.monotonic() - self.warning_seen_at > 10:
                snapshot = read_task_status(task, paused=self.paused)
                snapshot = snapshot.__class__(
                    task_name=snapshot.task_name,
                    account=snapshot.account,
                    stage=snapshot.stage,
                    detail=snapshot.detail,
                    elapsed_seconds=snapshot.elapsed_seconds,
                    level="running",
                    message=snapshot.detail,
                    completed_count=snapshot.completed_count,
                )
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
        # This prevents even a one-tick flash inside the desktop BitBlt region.
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
```

The implementation may factor the warning downgrade into a small helper, but it must preserve the exact public interfaces and four-line output.

- [ ] **Step 5: Integrate the window into the project-owned MainWindow**

In `custom_ok/ok/gui/MainWindow.py`, immediately after assigning `self.executor`, create and retain the status window. Failure is isolated because an optional monitor must never prevent the main application from starting:

```python
self.task_status_window = None
try:
    from src.gui.TaskStatusWindow import TaskStatusWindow
    self.task_status_window = TaskStatusWindow(executor)
    QApplication.instance().aboutToQuit.connect(self.task_status_window.shutdown)
except Exception as error:
    logger.warning(f"任务状态窗初始化失败，主任务继续运行：{error}")
```

Do not parent the tool window to MainWindow; it must remain visible when the main application window is minimized to the tray.

- [ ] **Step 6: Run status and MainWindow UI tests**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestTaskStatusWindow.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestMainWindowStartup.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestFiveSectionMainWindow.py
```

Expected: all PASS in offscreen/test doubles; no GUI test launches the game.

- [ ] **Step 7: Commit the status window**

```powershell
git add -- src/gui/TaskStatusWindow.py tests/TestTaskStatusWindow.py custom_ok/ok/gui/MainWindow.py run_tests.ps1
git diff --cached --name-only
git commit -m "feat: show minimal task status window"
```

Expected: no installed `.venv` file and no Android path staged.

---

### Task 4: Publish Account, Daily, and Nightmare Status

**Files:**
- Modify: `src/task/MultiAccountDailyTask.py:709-823, 957-1044, 2493-2518`
- Modify: `src/task/DailyTask.py:297-375`
- Modify: `src/task/NightmareNestTask.py:20-260`
- Modify: `tests/TestMultiAccountDailyTask.py`
- Modify: `tests/TestNightmareNestTask.py`
- Create: `tests/TestDailyTaskStatus.py`
- Modify: `run_tests.ps1: unit and image groups`

**Interfaces:**
- Consumes: `publish_task_status()` from Task 2.
- Produces structured `Status Account`, `Status Stage`, and `Status Detail` values for the parent task.
- Extends `NestTarget` with `display_name: str` and `ordinal: int` without changing its existing `box` and `cache_key` fields.

- [ ] **Step 1: Write failing task-publication tests**

Add tests covering these exact outcomes:

```python
def test_nest_target_keeps_the_display_name_and_ordinal(self):
    target = NestTarget(
        object(),
        "go_nest:41:10",
        display_name="落渊南丘残象聚落",
        ordinal=1,
    )
    assert target.display_name == "落渊南丘残象聚落"
    assert target.ordinal == 1


def test_logout_start_publishes_account_switch_status(self):
    published = []
    task = MultiAccountDailyTask.__new__(MultiAccountDailyTask)
    task.integrity_service = None
    task._logout_state = lambda: "login"
    task.log_info = lambda *_args, **_kwargs: None
    task.tr = lambda value: value
    task._publish_status = lambda **values: published.append(values)
    assert MultiAccountDailyTask._switch_to_login(task) is True
    assert {"stage": "账号切换", "detail": "正在退出当前账号"} in published
```

Create `tests/TestDailyTaskStatus.py` with a lightweight fake that calls the new helper methods rather than running game actions:

```python
import unittest
from unittest.mock import patch

from src.task.DailyTask import DailyTask


class TestDailyTaskStatus(unittest.TestCase):
    def test_publish_daily_stage_includes_active_account(self):
        task = DailyTask.__new__(DailyTask)
        task.get_active_profile_name = lambda: "A3"
        with patch("src.task.DailyTask.publish_task_status") as publish:
            task._publish_daily_stage("清理体力", "无音区")
        publish.assert_called_once_with(
            task,
            account="A3",
            stage="清理体力",
            detail="无音区",
        )


if __name__ == "__main__":
    unittest.main()
```

Register `TestDailyTaskStatus.py` in the `unit` group.

- [ ] **Step 2: Run the new tests and verify they fail**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestDailyTaskStatus.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestNightmareNestTask.py
```

Expected: FAIL because the status helpers and NestTarget display fields are absent.

- [ ] **Step 3: Add small publication wrappers**

In `MultiAccountDailyTask.py`:

```python
from src.task_status import publish_task_status


def _publish_status(self, *, account=None, stage=None, detail=None):
    publish_task_status(
        self,
        account=profile_status_label(account) if account else None,
        stage=stage,
        detail=detail,
    )
```

In `DailyTask.py`:

```python
from src.account_identity import short_profile_name
from src.task_status import publish_task_status


def _publish_daily_stage(self, stage, detail=""):
    account = short_profile_name(self.get_active_profile_name()) or "账号"
    publish_task_status(
        self,
        account=account,
        stage=stage,
        detail=detail,
    )
```

NightmareNestTask calls `publish_task_status(self, stage="刷梦魇巢穴", detail=...)` directly; the shared publisher routes it to the active DailyTask or MultiAccountDailyTask.

- [ ] **Step 4: Publish the minimal multi-account stages**

Add publication immediately before the corresponding existing actions:

```python
self._publish_status(stage="账号切换", detail="正在识别当前账号")
self._publish_status(
    account=next_account,
    stage="每日任务",
    detail=f"正在执行账号 {profile_status_label(next_account)}",
)
self._publish_status(
    account=profile_name,
    stage="账号切换",
    detail=f"正在选择账号 {profile_status_label(profile_name)}",
)
self._publish_status(
    account=profile_name,
    stage="账号切换",
    detail=f"正在等待账号 {profile_status_label(profile_name)} 进入主界面",
)
self._publish_status(
    account=first_account,
    stage="账号切换",
    detail=f"正在登录回起始账号 {profile_status_label(first_account)}",
)
```

At `_switch_to_login()` entry publish:

```python
self._publish_status(stage="账号切换", detail="正在退出当前账号")
```

Inside its state branches publish:

```python
if state == "confirm":
    self._publish_status(stage="账号切换", detail="正在确认退出登录")
elif state == "setting":
    self._publish_status(stage="账号切换", detail="正在点击退出登录")
elif state == "main":
    self._publish_status(stage="账号切换", detail="正在打开设置页")
elif state == "unknown":
    self._publish_status(stage="账号切换", detail="等待界面稳定")
```

- [ ] **Step 5: Publish the minimal DailyTask stages**

Before each existing block, call:

```python
self._publish_daily_stage("每日任务", "正在确认游戏主界面")
self._publish_daily_stage("每日任务", "正在检查每日奖励和体力进度")
self._publish_daily_stage("刷梦魇巢穴", "正在打开梦魇页面")
stamina_labels = {
    self.support_tasks[0]: "无音区",
    self.support_tasks[1]: "凝素领域",
    self.support_tasks[2]: "模拟领域",
}
self._publish_daily_stage("清理体力", stamina_labels.get(target, str(target)))
self._publish_daily_stage("每日任务", "正在领取每日奖励")
self._publish_daily_stage("每日任务", "正在领取邮件")
self._publish_daily_stage("每周任务", "正在检查每周乐园")
self._publish_daily_stage("每周任务", "正在融合废弃声骸")
self._publish_daily_stage("每日任务", "任务已完成")
```

Only call states at existing control-flow boundaries; do not add polling or a second progress engine.

- [ ] **Step 6: Preserve Nightmare target names**

Change the dataclass to:

```python
@dataclass
class NestTarget:
    box: object
    cache_key: str
    display_name: str = "未知目标"
    ordinal: int = 0
```

In `find_nest()`, obtain the action name before mutating the target Box:

```python
action_name = self.queues[0].__name__ if self.queues else "unknown"
display_name = (
    nest_name
    if action_name == "go_nest"
    else f"梦魇拔除第 {nest_index} 项"
)
publish_task_status(
    self,
    stage="刷梦魇巢穴",
    detail=f"当前目标：{display_name}",
)
return NestTarget(
    count_box,
    cache_key,
    display_name=display_name,
    ordinal=nest_index,
)
```

Publish action details in `combat_nest()` and `_travel_to_nest_or_skip()`:

```python
publish_task_status(self, stage="刷梦魇巢穴", detail=f"{target_name} · 正在进入挑战")
publish_task_status(self, stage="刷梦魇巢穴", detail=f"{target_name} · 正在传送")
publish_task_status(self, stage="刷梦魇巢穴", detail=f"{target_name} · 正在战斗")
publish_task_status(self, stage="刷梦魇巢穴", detail=f"{target_name} · 正在拾取声骸")
publish_task_status(self, stage="刷梦魇巢穴", detail=f"{target_name} · 不可到达，已跳过")
```

Use `nest.display_name` when `nest` is a NestTarget and `"当前目标"` otherwise. Do not OCR or invent unverified dream-purification names.

- [ ] **Step 7: Run task status regressions**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestDailyTaskStatus.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestNightmareNestTask.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestMultiAccountDailyTask.py
```

Expected: PASS; no fake permits real SendInput or game startup.

- [ ] **Step 8: Commit task publications**

```powershell
git add -- src/task/MultiAccountDailyTask.py src/task/DailyTask.py src/task/NightmareNestTask.py tests/TestMultiAccountDailyTask.py tests/TestNightmareNestTask.py tests/TestDailyTaskStatus.py run_tests.ps1
git diff --cached --name-only
git commit -m "feat: publish account and daily task status"
```

Expected: no Android paths staged.

---

### Task 5: Add the Task-Scoped Foreground Logout Capture Session

**Files:**
- Create: `src/logout_capture.py`
- Create: `tests/TestLogoutCapture.py`
- Modify: `run_tests.ps1: unit group`

**Interfaces:**
- Consumes:
  - ok-script `ForegroundBitBltCaptureMethod`
  - `HwndWindow.is_foreground()`
  - `HwndWindow.get_capture_origin()`
  - `HwndWindow.hwnd`
  - executor `exit_event`.
- Produces:
  - `CaptureSample(frame, origin, hwnd, source, captured_at)`
  - `ObservedBox(box, sample)`
  - `LogoutCaptureSession(hwnd_window, exit_event, capture_factory=ForegroundBitBltCaptureMethod)`
  - `LogoutCaptureSession.capture_main() -> CaptureSample | None`
  - `LogoutCaptureSession.last_reason: str`
  - idempotent `LogoutCaptureSession.close()` and context-manager methods.

- [ ] **Step 1: Write failing capture-session tests**

Create `tests/TestLogoutCapture.py`:

```python
import threading
import unittest

import numpy as np

from src.logout_capture import LogoutCaptureSession


class FakeHwndWindow:
    hwnd = 77
    exists = True

    def is_foreground(self):
        return True

    def get_capture_origin(self):
        return 100, 200


class FakeCapture:
    def __init__(self, hwnd_window, frame):
        self.hwnd_window = hwnd_window
        self.frame = frame
        self.exit_event = None
        self.closed = 0

    def get_frame(self):
        return self.frame

    def close(self):
        self.closed += 1


class TestLogoutCapture(unittest.TestCase):
    def test_valid_foreground_frame_returns_live_origin(self):
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        frame[20:40, 30:60] = 255
        created = []

        def factory(hwnd_window):
            capture = FakeCapture(hwnd_window, frame)
            created.append(capture)
            return capture

        session = LogoutCaptureSession(
            FakeHwndWindow(),
            threading.Event(),
            capture_factory=factory,
        )
        sample = session.capture_main()

        self.assertIs(frame, sample.frame)
        self.assertEqual((100, 200), sample.origin)
        self.assertEqual(77, sample.hwnd)
        self.assertEqual("foreground_bitblt", sample.source)
        session.close()
        session.close()
        self.assertEqual(1, created[0].closed)

    def test_pure_color_frame_is_rejected(self):
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        session = LogoutCaptureSession(
            FakeHwndWindow(),
            threading.Event(),
            capture_factory=lambda hwnd: FakeCapture(hwnd, frame),
        )
        self.assertIsNone(session.capture_main())
        self.assertEqual("pure-color-frame", session.last_reason)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Register and run the failing test**

Add `TestLogoutCapture.py` to the `unit` group, then run:

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestLogoutCapture.py
```

Expected: FAIL because `src.logout_capture` does not exist.

- [ ] **Step 3: Implement the isolated capture session**

Create `src/logout_capture.py`:

```python
from dataclasses import dataclass
import time

from ok.device.capture_methods.bitblt import ForegroundBitBltCaptureMethod
from ok.util.color import is_close_to_pure_color


@dataclass(frozen=True)
class CaptureSample:
    frame: object
    origin: tuple[int, int]
    hwnd: int
    source: str
    captured_at: float


@dataclass(frozen=True)
class ObservedBox:
    box: object
    sample: CaptureSample


class LogoutCaptureSession:
    def __init__(
        self,
        hwnd_window,
        exit_event,
        capture_factory=ForegroundBitBltCaptureMethod,
    ):
        self.hwnd_window = hwnd_window
        self.exit_event = exit_event
        self.capture = capture_factory(hwnd_window)
        self.capture.exit_event = exit_event
        self.last_reason = ""
        self.closed = False

    def capture_main(self):
        if self.closed:
            self.last_reason = "capture-session-closed"
            return None
        if not self.hwnd_window.is_foreground():
            self.last_reason = "main-window-not-foreground"
            return None
        try:
            frame = self.capture.get_frame()
        except Exception as error:
            self.last_reason = f"capture-error-{type(error).__name__}"
            return None
        if frame is None:
            self.last_reason = "empty-frame"
            return None
        if frame.shape[0] <= 10 or frame.shape[1] <= 10:
            self.last_reason = "invalid-frame-size"
            return None
        if is_close_to_pure_color(frame):
            self.last_reason = "pure-color-frame"
            return None
        if not self.hwnd_window.is_foreground():
            self.last_reason = "foreground-changed-after-capture"
            return None
        origin = self.hwnd_window.get_capture_origin()
        if not origin:
            self.last_reason = "missing-capture-origin"
            return None
        self.last_reason = ""
        return CaptureSample(
            frame=frame,
            origin=(int(origin[0]), int(origin[1])),
            hwnd=int(self.hwnd_window.hwnd),
            source="foreground_bitblt",
            captured_at=time.monotonic(),
        )

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.capture.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False
```

- [ ] **Step 4: Run capture tests**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestLogoutCapture.py
```

Expected: PASS.

- [ ] **Step 5: Commit the capture session**

```powershell
git add -- src/logout_capture.py tests/TestLogoutCapture.py run_tests.ps1
git diff --cached --name-only
git commit -m "feat: add scoped foreground logout capture"
```

Expected: no `config.py` capture backend change and no Android path staged.

---

### Task 6: Route the Logout State Machine Through Explicit Capture Samples

**Files:**
- Modify: `src/task/MultiAccountDailyTask.py:957-1044, 1535-1645, 2584-2615`
- Modify: `src/task/BaseWWTask.py:851-853, 985-1006`
- Modify: `tests/TestMultiAccountDailyTask.py`
- Modify: `tests/TestWaitLogin.py`

**Interfaces:**
- Consumes `LogoutCaptureSession`, `CaptureSample`, and `ObservedBox` from Task 5.
- Produces:
  - `MultiAccountDailyTask._create_logout_capture_session() -> context manager yielding LogoutCaptureSession | None`
  - `MultiAccountDailyTask._capture_logout_main_sample(session) -> CaptureSample | None`
  - `MultiAccountDailyTask._logout_state(capture_session=None) -> str`
  - `MultiAccountDailyTask._find_logout_button_target(capture_session=None) -> ObservedBox | None`
  - `BaseWWTask.in_team(frame=None)` and `BaseWWTask.in_team_and_world(frame=None)`.
- Preserves default behavior for callers that omit `capture_session` or `frame`.

- [ ] **Step 1: Add failing explicit-frame and cleanup tests**

Add `from src.logout_capture import CaptureSample, ObservedBox` beside the existing imports, then add these focused methods to the existing `unittest.TestCase` class in `tests/TestMultiAccountDailyTask.py`:

```python
def test_logout_state_uses_foreground_frame_for_features_and_origin(self):
    frame = object()
    sample = CaptureSample(frame, (100, 200), 77, "foreground_bitblt", 1.0)
    observed_frames = []

    class FakeTask:
        _logout_state = MultiAccountDailyTask._logout_state
        _capture_logout_main_sample = lambda self, session: sample
        _find_login_dialog = staticmethod(lambda: (0, None))
        _ocr_login_dialog = staticmethod(lambda: None)
        do_find_account_drop_down = lambda self, **kwargs: None
        wait_feature = staticmethod(lambda *args, **kwargs: None)
        in_team_and_world = staticmethod(lambda frame=None: True)

        def find_one(self, feature, **kwargs):
            observed_frames.append(kwargs.get("frame"))
            return None

    assert FakeTask()._logout_state(object()) == "main"
    assert observed_frames == [frame, frame]


def test_logout_capture_session_closes_when_task_is_stopped(self):
    closed = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            closed.append(True)

    task = MultiAccountDailyTask.__new__(MultiAccountDailyTask)
    task.integrity_service = None
    task._create_logout_capture_session = lambda: FakeSession()
    task._logout_state = lambda session=None: (_ for _ in ()).throw(TaskDisabledException())
    task._publish_status = lambda **_values: None
    task.log_info = lambda *_args, **_kwargs: None
    task.tr = lambda value: value

    with self.assertRaises(TaskDisabledException):
        MultiAccountDailyTask._switch_to_login(task)
    self.assertEqual([True], closed)
```

Add tests asserting:

- visible `#32770` login dialog OCR is checked before the foreground main frame;
- pure-color ForegroundBitBlt causes one WGC fallback sample and records a warning;
- `ObservedBox.sample.origin` is passed to the SendInput click conversion;
- no test calls `DeviceManager.set_capture()`;
- all existing fake tasks that call `_logout_state()` without a session still work.

- [ ] **Step 2: Run the focused tests and verify they fail**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestMultiAccountDailyTask.py
```

Expected: new tests FAIL because explicit capture samples are not wired.

- [ ] **Step 3: Allow feature checks against an explicit frame**

Change `BaseWWTask` signatures without changing existing callers:

```python
def in_team_and_world(self, frame=None):
    return self.in_team(frame=frame)[0]


def in_team(self, frame=None):
    c1 = self.find_one("char_1_text", threshold=0.8, frame=frame)
    c2 = self.find_one("char_2_text", threshold=0.8, frame=frame)
    c3 = self.find_one("char_3_text", threshold=0.8, frame=frame)
    arr = [c1, c2, c3]
    current = -1
    exist_count = 0
    for index, box in enumerate(arr):
        if box is None:
            if current == -1:
                current = index
        else:
            exist_count += 1
    if exist_count in (1, 2):
        self.logged_in = True
        return True, current, exist_count + 1
    return False, -1, exist_count + 1
```

- [ ] **Step 4: Create the capture session without touching global WGC**

Add:

```python
from contextlib import nullcontext
from src.logout_capture import CaptureSample, LogoutCaptureSession, ObservedBox


def _create_logout_capture_session(self):
    if getattr(self, "_android_boundary", lambda: None)() is not None:
        return nullcontext(None)
    try:
        return LogoutCaptureSession(
            self.hwnd,
            self.executor.exit_event,
        )
    except Exception as error:
        self.log_warning(f"退登前台截图初始化失败，保留 WGC：{error}")
        return nullcontext(None)
```

Do not access `executor.device_manager.set_capture`.

- [ ] **Step 5: Implement foreground-first with WGC fallback**

Add:

```python
def _capture_logout_main_sample(self, capture_session):
    main_hwnd, unused_pid = self._main_window_identity()
    if not main_hwnd:
        return None
    if capture_session is not None and self._bring_account_window_to_front(main_hwnd):
        self.sleep(0.2)
        sample = capture_session.capture_main()
        if sample is not None:
            return sample
        self.log_warning(
            f"退登前台截图不可用（{capture_session.last_reason}），本轮回退 WGC"
        )
    frame = self.next_frame()
    if frame is None:
        return None
    origin = self.hwnd.get_capture_origin()
    if not origin:
        return None
    return CaptureSample(
        frame=frame,
        origin=(int(origin[0]), int(origin[1])),
        hwnd=int(main_hwnd),
        source="wgc",
        captured_at=time.monotonic(),
    )
```

- [ ] **Step 6: Prioritize the independent login dialog**

Extend `do_find_account_drop_down` to accept:

```python
def do_find_account_drop_down(self, main_frame=None, prefer_dialog=False):
```

When `prefer_dialog` is true:

1. call `_ocr_login_dialog()` first;
2. return immediately with `_login_in_dialog = True` on a valid dialog hit;
3. only then evaluate `self.ocr(frame=main_frame)`.

When omitted, retain the existing main-frame-first behavior for all login selection callers.

- [ ] **Step 7: Detect logout states from one explicit sample**

Change the method entry to:

```python
def _logout_state(self, capture_session=None):
    self._logout_confirm_target = None
    if self.do_find_account_drop_down(prefer_dialog=True) is not None:
        return "login"
    sample = self._capture_logout_main_sample(capture_session)
    if sample is None:
        return "unknown"
```

Use `frame=sample.frame` for:

- confirm feature lookup;
- setting feature lookup;
- `in_team_and_world(frame=sample.frame)`.

When confirm is found:

```python
self._logout_confirm_target = ObservedBox(confirm, sample)
return "confirm"
```

Remove the short `wait_feature` retry inside `_logout_state`; the outer 45-second loop already obtains a new explicit frame and is the single retry mechanism.

- [ ] **Step 8: OCR the logout button into an ObservedBox**

Replace the current frame-implicit helper with:

```python
def _find_logout_button_target(self, capture_session=None):
    sample = self._capture_logout_main_sample(capture_session)
    if sample is None:
        return None
    texts = self.ocr(frame=sample.frame)
    boxes = self.find_boxes(
        texts,
        boundary=self.box_of_screen(0.0, 0.72, 0.35, 1.0),
        match=LOGOUT_TEXTS,
    )
    return ObservedBox(boxes[0], sample) if boxes else None
```

Extend `_click_main_login_box` with an explicit origin:

```python
def _click_main_login_box(self, box, *, stage, after_sleep=0.5, origin=None):
    if box is None:
        return False
    main_hwnd, unused_pid = self._main_window_identity()
    if not main_hwnd or not self._bring_account_window_to_front(main_hwnd):
        return False
    point = (
        self._box_center_screen(box, origin)
        if origin is not None
        else self._main_box_center_screen(box)
    )
    if point is None:
        return False
    return bool(self._screen_click(
        *point,
        after_sleep=after_sleep,
        target_hwnd=main_hwnd,
    ))
```

Keep the existing evidence recording around the SendInput call; add `capture_source` to its detail when available.

- [ ] **Step 9: Own the session for the entire logout loop**

Wrap the existing loop through a compatibility context. Production instances own `_create_logout_capture_session`; older focused fakes that bind only `_switch_to_login` continue through `nullcontext(None)`:

```python
session_factory = getattr(self, "_create_logout_capture_session", None)
session_context = session_factory() if callable(session_factory) else nullcontext(None)
with session_context as capture_session:
    while time.monotonic() < deadline:
        state = (
            self._logout_state(capture_session)
            if capture_session is not None
            else self._logout_state()
        )
```

Use:

```python
target = self._logout_confirm_target
self._click_main_login_box(
    target.box,
    stage="logout_confirm",
    after_sleep=0.2,
    origin=target.sample.origin,
)
```

and:

```python
target = self._find_logout_button_target(capture_session)
self._click_main_login_box(
    target.box,
    stage="logout_button",
    after_sleep=1,
    origin=target.sample.origin,
)
```

Keep the existing 45-second deadline, consecutive three-action budgets, unknown-state no-input rule, screenshot-on-final-failure behavior, and TaskDisabledException propagation.

- [ ] **Step 10: Run logout, login, and input regressions**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestMultiAccountDailyTask.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestWaitLogin.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestWin32LoginInput.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestAccountSwitchEvidence.py
```

Expected: all PASS, no real Win32 delivery.

- [ ] **Step 11: Prove prohibited global switching was not introduced**

```powershell
rg -n "set_capture|selected_method|DeviceManager" src/logout_capture.py src/task/MultiAccountDailyTask.py
```

Expected: no `set_capture` call in either implementation file.

- [ ] **Step 12: Commit explicit logout capture routing**

```powershell
git add -- src/task/MultiAccountDailyTask.py src/task/BaseWWTask.py tests/TestMultiAccountDailyTask.py tests/TestWaitLogin.py
git diff --cached --name-only
git commit -m "feat: use foreground capture during logout"
```

Expected: no Android paths staged.

---

### Task 7: Verify Error Persistence, Capture Safety, and Full Regression

**Files:**
- Modify: `tests/TestTaskStatusWindow.py`
- Modify: `tests/TestMultiAccountDailyTask.py`
- Modify: `tests/TestReleaseReadiness.py` if it asserts the current version or release notes.

**Interfaces:**
- Consumes all interfaces from Tasks 2-6.
- Produces regression evidence that status failures cannot stop tasks and capture failures cannot cause unsafe input.

- [ ] **Step 1: Add final error and safety tests**

Add tests asserting:

```python
def test_last_error_remains_visible_after_current_task_is_cleared(self):
    task = FakeTask()
    executor = FakeExecutor(task)
    task.info["Error"] = "登录界面等待超时"
    window = TaskStatusWindow(executor)
    window.on_task(task)
    executor.current_task = None
    window.on_task(None)
    window.refresh()
    assert "登录界面等待超时" in window.label.text()
    assert window.isVisible()
    window.shutdown()


def test_status_window_failure_does_not_change_task_state(self):
    task = FakeTask()
    executor = FakeExecutor(task)
    task.info_set = lambda key, value: (_ for _ in ()).throw(RuntimeError("ui unavailable"))
    publish_task_status(task, stage="账号切换", detail="等待界面稳定")
    assert executor.current_task is task
```

Add logout tests asserting:

- an unknown capture state sends neither ESC nor mouse input;
- an invalid foreground frame followed by a valid WGC frame can detect the state;
- an invalid foreground frame followed by no WGC frame remains unknown;
- the dialog BitBlt branch never uses the main-window origin;
- the task status window HWND is never accepted as a SendInput target.

- [ ] **Step 2: Run the new focused tests**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestTaskStatusWindow.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestMultiAccountDailyTask.py
```

Expected: PASS.

- [ ] **Step 3: Compile all modified Python modules**

```powershell
.\.venv\Scripts\python.exe -m py_compile src/task_status.py src/logout_capture.py src/gui/TaskStatusWindow.py src/task/BaseWWTask.py src/task/MultiAccountDailyTask.py src/task/DailyTask.py src/task/NightmareNestTask.py custom_ok/ok/gui/MainWindow.py
```

Expected: exit code 0.

- [ ] **Step 4: Run every registered test file in isolated processes**

```powershell
.\run_tests.ps1 -Group all
```

Expected: every registered test file passes. Do not replace this with an in-process unittest discovery run.

- [ ] **Step 5: Inspect the complete release diff**

```powershell
git status --short
git diff --stat d4ffe04a4b530653aed516f1743fcd6b3492ef01
git diff --check d4ffe04a4b530653aed516f1743fcd6b3492ef01
```

Expected:

- `git diff --check` produces no whitespace errors;
- only planned feature files plus the pre-existing Android dirty paths appear;
- no `.venv` file is modified;
- no real account identifier, phone number, or screenshot is added.

- [ ] **Step 6: Commit final regression adjustments**

```powershell
git add -- tests/TestTaskStatusWindow.py tests/TestMultiAccountDailyTask.py tests/TestReleaseReadiness.py
git diff --cached --name-only
git commit -m "test: verify task status and logout capture safety"
```

If `tests/TestReleaseReadiness.py` did not require modification, omit it from the `git add` command. Never add a nonexistent or unchanged file merely to match the plan.

---

### Task 8: Publish 1.22.00 to the Correct GitHub Repository

**Files:**
- No new source changes.
- Verify all files committed by Tasks 1-7.

**Interfaces:**
- Consumes verified `master` release commit with product version `1.22.00`.
- Produces remote `origin/master` and annotated tag `v1.22.00` pointing to the same final commit.

- [ ] **Step 1: Verify only the user's Android work remains uncommitted**

```powershell
git status --short
git diff --cached --name-only
```

Expected:

- staged output is empty;
- remaining modified/untracked paths are exactly the pre-existing Android work;
- all `1.22.00` feature files are committed.

- [ ] **Step 2: Verify release metadata and prohibited paths**

```powershell
rg -n "version = \"1\.22\.00\"|V1\.22\.00|## 1\.22\.00" config.py custom_ok/ok/gui/about/AboutTab.py 更新日志.md
rg -n "SetCursorPos|mouse_event|interaction_mode='postmessage'|方式=PostMessage" src/task/BaseWWTask.py src/task/MultiAccountDailyTask.py src/task/DailyTask.py
```

Expected:

- version text is synchronized;
- no old login mouse fallback is reintroduced.

- [ ] **Step 3: Create the annotated release tag**

```powershell
git tag -a v1.22.00 -m "v1.22.00"
```

Expected: tag creation succeeds and `git show --no-patch v1.22.00` reports the final release commit.

- [ ] **Step 4: Push master and tag to the correct remote**

```powershell
git push origin master
git push origin v1.22.00
```

Expected: both pushes succeed against `xihuojun2020-tech/okww-custom`.

- [ ] **Step 5: Verify remote branch and tag**

```powershell
git fetch origin --tags
git rev-parse HEAD
git rev-parse origin/master
git rev-parse "v1.22.00^{}"
```

Expected: all three hashes are identical.

- [ ] **Step 6: Record the no-game validation boundary**

The delivery report must state:

- all automated tests used fakes, static frames, or Qt offscreen mode;
- no game process was launched, focused, captured, clicked, logged out, or switched;
- real-world ForegroundBitBlt behavior still requires later user-observed runtime evidence;
- the prior Android work remains uncommitted and untouched.

---

## Plan Self-Review Checklist

- [x] Every design requirement maps to a task:
  - foreground-first logout capture: Tasks 5-7;
  - WGC fallback without global switching: Tasks 5-7;
  - dialog HWND BitBlt preservation: Task 6;
  - status account/stage/detail: Tasks 2 and 4;
  - transparent status window: Task 3;
  - warnings and persistent errors: Tasks 2, 3, and 7;
  - capture-safe placement and exclusion: Tasks 2, 3, and 7;
  - version, tests, tag, push: Tasks 1, 7, and 8.
- [x] Search the plan for `TBD`, `TODO`, `implement later`, and `similar to`; none remain outside this self-review statement.
- [x] Verify `CaptureSample`, `ObservedBox`, `LogoutCaptureSession`, `TaskStatusSnapshot`, and all status-key names match in every task.
- [x] Verify every Python command uses `.\.venv\Scripts\python.exe`.
- [x] Verify no step starts or operates the game.
- [x] Verify no step stages the existing Android work.
