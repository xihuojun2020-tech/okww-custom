# PC 登录与账号切换 SendInput 设计规格

## 背景与结论

本项目只支持 PC 版鸣潮的登录、退登与账号切换，不再考虑手机模拟器。游戏主画面通常由
`UnrealWindow` 承载，账号登录器还可能创建同进程的独立 `#32770` 顶层窗口以及
`ComboBox`、`ComboLBox`、`Button` 子窗口或弹出窗口。

WGC 继续固定捕获游戏主窗口。不能为了独立登录窗动态重绑 WGC：重绑会重建帧池，而且部分
`#32770` 窗口会令 `CreateForWindow` 返回 `0x80070057`。独立登录窗口及其控件改用 HWND
客户区 BitBlt；两类画面分别使用自己的实时坐标原点，不能混用。

## 目标

1. 仅替换 PC 登录、退登和账号切换状态机内的鼠标点击。
2. 战斗、键盘和普通任务继续使用全局 `PostMessage` 交互配置。
3. 登录鼠标点击统一经过校验后的 Win32 `SendInput`，执行期间允许强制正确窗口到前台。
4. 主窗口和独立登录窗均以游戏主窗口 PID 为信任根。
5. 输入投递 `delivered` 与界面确认 `confirmed` 分开记录和判断。
6. 正式多账号任务与 `TestAccountSwitchTask` 继续复用同一个 `LoginFlowService` 编排入口。
7. 所有验证只使用伪 Win32 API、伪 OCR 帧和状态机测试；不启动、聚焦或操控游戏。

## 非目标

- 不支持模拟器、ADB 登录或移动端鸣潮。
- 不修改 WGC 主窗口捕获目标。
- 不修改战斗点击、键盘输入或普通任务点击。
- 不增加驱动、全局 Hook、DLL 注入或第三方依赖。
- 不允许登录点击回退到 `PostMessage`、固定屏幕坐标、固定账号行号或缓存 OCR 坐标。

## Win32 输入边界

新增 `src/win32_login_input.py`，模块只验证一次点击并投递输入，不包含 OCR、账号匹配或业务重试。
公开接口为：

```python
@dataclass(frozen=True)
class ForegroundResult:
    ready: bool
    reason: str
    target_hwnd: int
    foreground_hwnd: int
    expected_pid: int


@dataclass(frozen=True)
class LoginClickDelivery:
    delivered: bool
    reason: str
    target_hwnd: int
    foreground_hwnd: int
    hit_hwnd: int
    expected_pid: int
    point: tuple[int, int]


def force_foreground(target_hwnd: int, expected_pid: int, *, api=None) -> ForegroundResult: ...


def send_input_click(
    target_hwnd: int,
    expected_pid: int,
    point: tuple[int, int],
    *,
    api=None,
) -> LoginClickDelivery: ...
```

`api` 仅用于注入测试替身。生产实现使用标准库 `ctypes` 调用 user32：

1. 验证目标 HWND 存在、可见、已启用，且 PID 等于游戏主进程 PID。
2. 使用 `GetAncestor(hwnd, GA_ROOT)` 找到目标自己的实际顶层窗口。
3. 对最小化窗口执行 `ShowWindow(SW_RESTORE)`。
4. 必要时以 `AttachThreadInput` 临时连接当前、目标和现前台线程。
5. 对 `GA_ROOT` 调用 `BringWindowToTop` 与 `SetForegroundWindow`，随后在 `finally` 中解除线程连接。
6. 重新读取前台窗口，只有其 `GA_ROOT` 与目标顶层窗口相同且 PID 匹配时才允许继续。

`GA_ROOTOWNER` 只用于判断目标与 `WindowFromPoint` 命中窗口是否属于同一窗口关系链，不能用作
实际置前对象，否则独立 `#32770` 会被折叠成游戏主窗口。

点击前还必须验证：

- 点击点位于 Windows 虚拟桌面范围内；
- 点击点位于目标 HWND 的实时窗口矩形内；
- `WindowFromPoint` 命中有效 HWND；
- 命中 HWND 的 PID 与游戏 PID 相同；
- 命中 HWND 是目标本身、父子窗口或同一 root-owner 关系链。

通过后一次提交三个 `INPUT`：虚拟桌面绝对坐标移动、左键按下、左键释放。只有 `SendInput`
返回 3 才是 `delivered=True`。

## 捕获和坐标

- 主游戏窗口和内嵌登录：继续使用 WGC，OCR 框以 `HwndWindow.get_capture_origin()` 换算屏幕坐标。
- 独立 `#32770`、`ComboBox`、`ComboLBox`：使用各自 HWND 的客户区 BitBlt，OCR 框以
  `ClientToScreen(hwnd, (0, 0))` 换算屏幕坐标。
- `_find_login_dialog()` 只返回同 PID、可见、尺寸有效的 `#32770`。
- `_find_control_hwnd()` 同时枚举对话框子窗口和同 PID 顶层弹出窗口；控件必须与选定登录对话框
  有父子或 root-owner 关系。
- BitBlt 的 DC、兼容 DC 和位图对象全部在 `finally` 中释放。

## 生产流程

### 打开账号列表

重新发现实际 `ComboBox` 或从新 WGC 帧取得主窗口下拉框，强制对应 HWND 到前台并执行
`SendInput`。投递成功仅记录 `delivered=True`；只有 `ComboLBox` 可见或 OCR 至少出现两个账号
条目才记录 `confirmed=True`。

### 选择账号

优先捕获 `ComboLBox` 客户区并在同一帧完成 OCR、身份映射和坐标换算。没有 `ComboLBox` 时，
内嵌登录只能使用新 WGC 帧。点击后必须观察到列表收起且目标账号连续两次识别一致；否则重新发现
窗口、重新 OCR 并按预算重试，不能改走 `PostMessage`。

### 点击登录

每次先执行现有 `_confirm_target_before_login()`。独立登录窗使用新 BitBlt 帧，内嵌登录使用新
WGC 帧，然后对相应 HWND 执行 `SendInput`。只有账号下拉框稳定消失并开始界面转换才是
`confirmed=True`；三次仍未确认则安全停止。

### 退登

ESC 键继续使用现有键盘交互。鼠标操作改为：

- 退登确认框使用当前帧识别出的确认框实际坐标；
- 设置页重新 OCR 匹配“退出登录/退出登入/退出登錄/登出/Log Out/Logout”；
- 删除固定归一化坐标和全桌面截图点击；
- 每次点击后继续由 `_logout_state()` 确认状态推进，未知状态不发送鼠标输入。

`BaseWWTask.wait_login()` 的 PC 公告关闭、登录、隐私同意、更新确认、开始游戏和切换账号入口均
使用相同边界。`DailyTask` 单账号自动退登通过已注册的 `MultiAccountDailyTask._switch_to_login()`
复用正式状态机。`WWOneTimeTask` 删除旧全屏截图、固定坐标、`SetCursorPos` 和 `mouse_event` 实现。

## 现有架构兼容

`MultiAccountDailyTask.switch_to_account()` 继续委托 `LoginFlowService.switch_to_account()`；服务仍
负责完整性门禁、退登、等待登录界面、选号、登录前复核、点击登录和 `ensure_main()`。本改动只替换
服务所调用的任务级鼠标原语和确认逻辑，不复制第二套账号切换编排。

默认连续账号切换测试顺序保持 A1、A3、A4，按精确方案短名解析，并继续覆盖配置的备用登录名和
掩码手机号身份。

## 失败策略

- 前台、PID、坐标或命中窗口校验失败：不投递，记录原因并按状态机预算重试。
- 置前后 HWND 失效：重新发现窗口并重新 OCR，不使用旧句柄或旧坐标。
- WGC 主帧无登录特征：检查独立登录窗 BitBlt；两路均无特征则等待。
- BitBlt 失败：释放资源并返回无帧，不切换 WGC 目标。
- OCR 无目标或身份歧义：不点击并沿用现有安全停止行为。
- `delivered=True` 但界面未确认：不得进入下一状态，重新发现并重试。

## 测试与发布

测试注入伪 Win32 API，覆盖前台成功/失败、PID 不符、隐藏/禁用窗口、虚拟桌面负原点、点位越界、
命中无关窗口、部分投递和完整投递；任务测试覆盖主窗口、`#32770`、`ComboBox`、`ComboLBox` 的
目标 HWND 与坐标原点，确认不存在登录 `PostMessage` 回退，并验证 `delivered`/`confirmed` 分离。

不执行真实账号切换任务，不调用真实 `SendInput`，不启动、聚焦或操作游戏。该输入边界改造为中等
变更，版本从 `1.20.02` 升级为 `1.21.00`，同步 `config.py`、About 和 `更新日志.md`。验证后提交
正确仓库 `master`，创建注释标签 `v1.21.00` 并推送。只有远端新提交和标签核验成功后，才删除误推
的 Better Wuwa 远程分支 `codex/mumu-adb-migration` 与标签 `v0.01.01`、`v0.02.00`。
