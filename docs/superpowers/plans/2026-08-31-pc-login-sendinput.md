# PC 登录与账号切换 SendInput 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留主窗口 WGC、独立登录窗 BitBlt 和现有 `LoginFlowService` 编排的前提下，将 PC 登录、退登和账号切换鼠标点击统一迁移到经过窗口校验的 Win32 `SendInput`。

**Architecture:** `src/win32_login_input.py` 是唯一系统鼠标输入边界，只负责 HWND/PID/前台/坐标/命中窗口校验和一次投递。`MultiAccountDailyTask` 继续负责窗口发现、OCR、账号身份、重试和界面确认，`LoginFlowService` 继续负责生产编排；`BaseWWTask.wait_login()` 和单账号退登复用同一边界与正式状态机。

**Tech Stack:** Python 3.12、标准库 `ctypes`、现有 pywin32/OpenCV、`unittest`、Windows user32/GDI。

**Spec:** `docs/superpowers/specs/2026-08-31-pc-login-sendinput-design.md`

## Global Constraints

- 仅支持 PC 鸣潮登录；不实现模拟器或 ADB 登录点击。
- 保持 `config.py` 的全局 `interaction: PostMessage`；战斗、键盘和普通任务不在本次范围。
- 所有登录鼠标点击使用 `SendInput`，不得回退到 `PostMessage`、固定坐标、驱动、Hook 或 DLL 注入。
- WGC 固定主游戏 HWND；独立 `#32770`、`ComboBox`、`ComboLBox` 使用各自 BitBlt 帧和 `ClientToScreen` 原点。
- 投递与界面确认分离；任何 `delivered=True` 都不能直接代表选号或登录成功。
- 测试只注入伪 Win32/OCR/状态；禁止启动、聚焦、操作游戏或调用真实 `SendInput`。
- `TestAccountSwitchTask` 继续复用生产选择、别名匹配、核验、重试、退登和登录方法；默认精确短名顺序为 A1、A3、A4。
- 中等版本固定为 `1.21.00`；同步 `config.py`、About、更新日志和版本一致性测试。
- 不暂存现有 `src/android/`、`android/agent-app/` 和 Android 规格/计划改动。

---

### Task 1: 建立可注入的 Win32 输入边界

**Files:**
- Create: `src/win32_login_input.py`
- Create: `tests/TestWin32LoginInput.py`

**Interfaces:**
- Consumes: 目标 HWND、可信游戏 PID、屏幕坐标。
- Produces: `ForegroundResult`、`LoginClickDelivery`、`force_foreground()`、`send_input_click()`。

- [x] **Step 1: 先加入伪 Win32 失败测试**

测试替身以字典保存窗口 PID、矩形、可见/启用状态、父子与 root-owner 关系；
`send_mouse_click()` 只记录参数。覆盖无效/隐藏/禁用 HWND、PID 不符、前台拒绝、虚拟桌面越界、
目标矩形越界、无命中窗口、命中无关窗口和 `SendInput` 只返回 0～2。

- [x] **Step 2: 验证新测试因模块缺失而失败**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestWin32LoginInput -v
```

Expected: `ModuleNotFoundError: src.win32_login_input`。

- [x] **Step 3: 实现不可变结果和 ctypes 适配器**

实现规格中的两个 dataclass。`force_foreground()` 对 `GA_ROOT` 恢复、置前和复核；
`GA_ROOTOWNER` 只用于 `_same_window_tree()`。`send_input_click()` 校验实时窗口和
`WindowFromPoint`，再提交包含移动、左键按下、左键释放的三项 `INPUT` 数组。

- [x] **Step 4: 运行输入边界测试**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestWin32LoginInput -v
```

Expected: 全部通过，替身确认负虚拟桌面原点正确归一化，且没有真实鼠标输入。

### Task 2: 将任务级窗口发现、BitBlt 和系统点击接入新边界

**Files:**
- Modify: `src/task/MultiAccountDailyTask.py`
- Test: `tests/TestMultiAccountDailyTask.py`

**Interfaces:**
- Consumes: Task 1 的 `force_foreground()` 和 `send_input_click()`。
- Produces: `_main_window_identity() -> tuple[int, int]`、`_bring_account_window_to_front(target_hwnd=None) -> bool`、`_screen_click(x, y, *, target_hwnd, after_sleep=0.5) -> bool`。

- [x] **Step 1: 增加显式 HWND 路由测试**

断言 `_screen_click(300, 400, target_hwnd=77)` 调用 `send_input_click(77, game_pid, (300, 400))`；
任务停用或投递失败时返回 `False`。断言独立对话框不读取主窗口 capture origin。

- [x] **Step 2: 接入主窗口身份和强制前台**

从 `self.hwnd.hwnd` 读取可信主 HWND/PID。`_bring_account_window_to_front()` 将实际主窗口、对话框或
控件 HWND 传给 `force_foreground()`，不能调用 owner 主窗口代替独立 `#32770`。

- [x] **Step 3: 加固窗口发现和 BitBlt 释放**

`_find_login_dialog()` 限定同 PID。`_find_control_hwnd()` 同时枚举对话框子窗口和相关顶层弹窗。
`_capture_hwnd_client()` 在 `finally` 中释放窗口 DC、MFC DC、兼容 DC 和位图。

- [x] **Step 4: 运行窗口路由聚焦测试**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestMultiAccountDailyTask -v
```

### Task 3: 迁移退登、账号列表、选号和登录点击

**Files:**
- Modify: `src/task/MultiAccountDailyTask.py`
- Modify: `tests/TestMultiAccountDailyTask.py`

**Interfaces:**
- Consumes: 现有 `LoginFlowService`、账号选择/核验服务和 Task 2 的窗口输入原语。
- Produces: 不含 `PostMessage` 回退的正式账号切换鼠标路径。

- [x] **Step 1: 写退登 OCR 与状态确认测试**

确认框必须以识别框坐标调用 `SendInput`；设置页只点击新 OCR 帧中的退出登录文本，找不到文本时不
点击固定坐标。`_logout_state()` 只观察，不能通过 `is_main()->wait_login()` 间接点击登录。

- [x] **Step 2: 写账号列表与选号投递/确认分离测试**

覆盖主窗口、`ComboBox`、`ComboLBox` 的目标 HWND；`delivered=True` 但列表未展开或账号未连续
两次一致时必须重试。任何登录路径调用 `self.click()` 都令测试失败。

- [x] **Step 3: 迁移退登鼠标点击**

增加 `LOGOUT_TEXTS`、`_find_logout_button_box()` 和 `_click_main_login_box()`；保留 ESC 键盘路径，
删除确认框 `click()` 和设置页 `(0.04, 0.96)`。

- [x] **Step 4: 迁移打开列表与账号选择**

每次投递前重新置前、发现 HWND 和 OCR。`ComboLBox` 优先；内嵌登录使用新 WGC 帧。删去
`interaction_mode='postmessage'` 及后备分支，证据写入 `delivered` 与 `confirmed`。

- [x] **Step 5: 迁移登录按钮**

独立对话框从新 BitBlt 帧找登录按钮，内嵌登录从新 WGC 帧找登录按钮。三次尝试都使用
`SendInput`，每次仍调用 `_confirm_target_before_login()`，并以控件消失确认转换。

- [x] **Step 6: 保留生产服务委托并运行状态机测试**

确认 `switch_to_account()` 仍只委托 `LoginFlowService`，测试任务仍调用生产入口。

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestMultiAccountDailyTask tests.TestAccountSwitch tests.TestAccountRuntimeIntegration tests.TestAccountSwitchEvidence -v
```

### Task 4: 迁移通用 PC 登录与单账号退登

**Files:**
- Modify: `src/task/BaseWWTask.py`
- Modify: `src/task/DailyTask.py`
- Modify: `src/task/WWOneTimeTask.py`
- Modify: `tests/TestWaitLogin.py`
- Modify: `tests/TestMultiAccountDailyTask.py`

**Interfaces:**
- Produces: `BaseWWTask._click_login_box()`；`DailyTask._logout_pc_after_daily()` 委托正式退登状态机。

- [x] **Step 1: 写通用登录 SendInput 测试**

主窗口 OCR 框以 WGC capture origin 换算，补丁替身断言调用 `send_input_click(main_hwnd, pid, point)`；
测试中的 `click()` 直接抛错，确保 PC 登录不经过 `PostMessage`。

- [x] **Step 2: 替换 `wait_login()` 的 PC 鼠标点击**

公告关闭、登录、隐私同意、更新确认、开始游戏和切换账号均调用 `_click_login_box()`。Android
分支若存在则保留原边界，不让 PC `SendInput` 跨入移动路径。

- [x] **Step 3: 单账号退登委托生产状态机**

`DailyTask` 取得已注册的 `MultiAccountDailyTask` 并调用 `_switch_to_login()`；未注册时明确失败。

- [x] **Step 4: 删除旧的一次性桌面点击实现**

从 `WWOneTimeTask` 删除全桌面截图、固定坐标、`SetCursorPos` 和 `mouse_event`，保留一次性任务启动
所需的鼠标重置和 `PostMessageInteraction.activate()`。

- [x] **Step 5: 运行聚焦测试**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestWaitLogin tests.TestMultiAccountDailyTask -v
```

### Task 5: 同步版本与产品说明

**Files:**
- Modify: `config.py`
- Modify: `custom_ok/ok/gui/about/AboutTab.py`
- Modify: `更新日志.md`
- Verify: `tests/TestReleaseReadiness.py`

- [x] **Step 1: 升级中等版本**

将 `1.20.02` 改为 `1.21.00`。About 首行说明 PC 登录/退登/切号使用校验后的 `SendInput`、独立登录
窗口使用自己的 HWND/BitBlt、测试不操作游戏。更新日志新增同版本正式条目。

- [x] **Step 2: 验证版本三处一致**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestReleaseReadiness -v
```

### Task 6: 非实机验证与范围检查

**Files:**
- Verify all files from Tasks 1-5.

- [x] **Step 1: 编译改动模块**

```powershell
.\.venv\Scripts\python.exe -m py_compile config.py src\win32_login_input.py src\task\BaseWWTask.py src\task\DailyTask.py src\task\MultiAccountDailyTask.py src\task\WWOneTimeTask.py
```

- [x] **Step 2: 运行聚焦伪 Win32/账号切换测试**

每个 `tests/Test*.py` 以独立 `.venv` Python 进程运行，避免 Qt 全局实例污染；不运行正式任务入口。

- [x] **Step 3: 扫描禁止路径**

```powershell
rg -n "SetCursorPos|mouse_event|interaction_mode='postmessage'|方式=PostMessage" src/task/BaseWWTask.py src/task/DailyTask.py src/task/MultiAccountDailyTask.py src/task/WWOneTimeTask.py
git diff --check
git status --short
```

Expected: 登录相关文件不存在旧系统鼠标或登录 PostMessage 降级；Android 用户改动仍未暂存。

### Task 7: 提交正确版本并清理远程 Better Wuwa 引用

**Files:**
- Stage only files from this plan.

- [ ] **Step 1: 精确暂存并审查**

使用 `git add -- <explicit files>`，随后检查 `git diff --cached --stat`、`--check` 和完整缓存差异；
不得暂存现有 Android 文件和目录。

- [ ] **Step 2: 提交并创建注释标签**

```powershell
git commit -m "feat: harden PC login clicks with SendInput"
git tag -a v1.21.00 -m "v1.21.00"
```

- [ ] **Step 3: 推送正确 `master` 与标签**

```powershell
git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 push origin master v1.21.00
```

- [ ] **Step 4: 核验后删除误推引用**

先用 `ls-remote` 确认 `master` 与 `v1.21.00^{}` 指向同一提交，再删除
`codex/mumu-adb-migration`、`v0.01.01` 和 `v0.02.00`。不删除 `okww-custom` 仓库。

- [ ] **Step 5: 最终远程核验**

再次执行 `ls-remote`：正确 `master`/`v1.21.00` 存在，三个 Better Wuwa 引用不存在。
