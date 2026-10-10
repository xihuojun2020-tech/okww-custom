# 原生迁移剩余消费者核查

核查日期：2026-10-11。对照当前 `1.97.73` 工作区，**不能宣称原魔改版所有行为均已迁移**。已接通的程序偏好、辅助服务恢复、语言和账号上下文不再作为缺口重复计算；仍有外部通知、UID 实时遮罩、启动前显卡后处理告警及部分旧窗口行为缺少原生消费者。

本报告由 `2026-10-11-gameframe-final-coverage-gaps.md` 的设置缺口继续核查。只读 `custom_ok/ok`、当前实际安装的 `.venv/Lib/site-packages/ok` / `pyappify` 源码，以及原生包、GameFrame 和更新服务；唯一写入为本文。语言代码和目录保持冻结。未导入旧应用、构造设备、运行游戏、操作系统输入、发送消息、连接 NAS 或重复运行测试。安装依赖仅用于确认旧版真实接口，不代表原生发行包应依赖本机 `.venv`。

“已迁移”表示存在设置来源和实际消费者；“尚未迁移”表示旧行为确有调用路径、原生没有等价路径；“明确不适用”表示旧发行器专属机制或本产品禁用的路径。任务注册、控件显示及方法存在本身均不计为完成。

## 1. Basic Options：逐项对照

旧字段的完整来源为 `.venv/Lib/site-packages/ok/util/GlobalConfig.py:51`；附加遮罩字段由 `register_basic_options(..., enable_blur=callable(config['blur_area']))` 注册，当前 `config.py:177` 提供实际 callable，故这三个字段确实属于本产品旧版设置。

| 字段 | 旧版实际消费者 | 当前原生消费者 / 状态 |
| --- | --- | --- |
| Auto Start Game When App Starts | 在已检查的 `src`、`custom_ok/ok`、安装的 `ok` Python 中仅发现定义；没有读取该键的启动路径 | **明确不作为已证实行为迁移**。`config.py:210` 的 `windows.start_exe=False` 是本产品明确的手动启动决定；应用打开恢复辅助服务是另一项行为，已由 `GameFrameWindow._restore_saved_session` 接通。 |
| Minimize Window to System Tray when Closing | `custom_ok/ok/gui/MainWindow.py:1006` 的 closeEvent 读取后隐藏窗口 | **已迁移**：`gameframe/desktop_controls.py:21` 导入旧值；`gameframe/gui.py:1262` 保留 close-to-tray、显式 Quit 与正常清理。 |
| Mute Game while in Background | 安装的 `ok/device/capture_methods/hwnd_window.py:75,189,353` 按窗口前台状态静音 | **已迁移**：`native_program_preferences.DEFAULTS` / 一次旧值导入；`gameframe/devices/windows_preferences.py:53` 按已选 PID 音频会话保存/恢复初始静音值；plugin 配置到实际 Windows device，host 主循环轮询。 |
| Auto Resize Game Window | `hwnd_window.try_resize_to` 和 `StartController.check_resolution` | **已迁移消费者**：`windows_preferences.py:48`、`WindowsDevice.resize_client`、manifest.window_preferences 的四档分辨率；不等同已证明所有旧捕获模式、越界居中和设备准备行为完全一致。 |
| Exit App when Game Exits | `hwnd_window.py:294` 检测窗口消失后通知 quit | **已迁移消费者**：`WindowsPreferences.poll` 检查原 PID/create-time 的真实退出；host 发 `target-exited`，GUI 执行退出。窗口暂时不可捕获不应当作进程退出。 |
| Use DirectML | 安装的 `ok/__init__.py:948` 读取 Yes/No/Auto 决定 OCR DML；旧 Auto 还查 NVIDIA 空闲显存 | **已迁移设置及真实推理消费者**：`src/vision/native_ocr_factory.py` 为真实 onnxocr detector/recognizer 创建 DML session。当前 Auto 依据 DmlExecutionProvider 可用性，和旧显存启发式不同；明确 Yes 不可用会失败。保存值经现有 Config 持久化，重启任务会话应用。 |
| Trigger Interval | `custom_ok/ok/task/TaskExecutor.py:613` 调度间隔 | **已迁移**：Program Preferences → `native_combat_host.py:591`，按毫秒等待服务调度。 |
| Start/Stop | `custom_ok/ok/gui/start/StartCard.py:151` 注册 WM_HOTKEY；`clicked():91` 在已暂停时调用 StartController.start，在运行时 pause | **部分迁移**：旧值导入且原生有暂停/恢复热键；`gameframe/gui.py:1259` 仅在已有进程时轮询，所以没有会话时通过热键启动的旧路径未恢复。当前名称“暂停 / 恢复热键”准确反映边界。 |
| Kill Launcher After Start | `custom_ok/ok/gui/MainWindow.py:635` 首次显示后调用 `pyappify.kill_pyappify`；可被移到 App Launcher 面板 | **明确不适用当前原生发行器**：native 无 PyAppify UI 进程或对应 API 绑定。不应把它误用为结束游戏启动器或终止任意进程。 |
| Launch with DX11 | 安装的 `ok/gui/StartController.py:179` 给 execute 传 `-dx11 -d3d11 -force-d3d11` | **当前产品路径不适用；偏好未迁移**：该读取在 start_device 内，当前 `windows.start_exe=False` 的 do_start 跳过 start_device。原生显式 `launch_command` 可包含用户设置的参数，但没有自动导入这个布尔项；不能称已经恢复旧 DX11 开关。 |
| Enable Blur / Blur Algorithm / Blur Interval | TaskExecutor 创建 BlurOverlayProcessor，从实际捕获帧调用 next_frame；通过 Qt signal 更新 OverlayWindow | **尚未迁移实时屏幕遮罩**。详见下一节。 |

以上旧值导入仅发生在显式选定资料根中；不会自行搜寻其他安装或 Windows 用户的配置。本轮不重复已经完成的语言、账号上下文和辅助服务恢复专项测试，也不将它们的完成推及其他设置。

## 2. 实时 UID 遮罩与截图遮罩是不同消费者

完整旧链路有源码证据：

1. 安装的 `ok/__init__.py:553` 按 `blur_area` 注册三个 Basic 字段；`:356` 创建 overlay view。
2. `custom_ok/ok/task/TaskExecutor.py:102` 构造 `BlurOverlayProcessor`，传入三个字段读取函数、blur/clear signal 和退出信号；`:271` 在拿到帧后调用 `next_frame`。
3. 安装的 `ok/gui/overlay/OverlayWindow.py:45` 连接 blur/clear signal；`ok/util/blur.py:118` 的 worker 按算法和间隔生成 patch，并根据游戏窗口可见性显示/清除。

原生现有 `src/runtime/native_screenshots.py:11` 会复制帧并涂黑身份区域后保存 PNG，具有实际截图隐私消费者；原生代码没有上述实时 overlay、算法选择或间隔消费者。**已遮罩诊断截图不能证明用于 OLED / 游戏屏幕遮罩的三个偏好已完成迁移**。不需要为了这次审计新增虚假开关；后续是否恢复实时覆盖层应单独明确。

## 3. Notification：只有系统托盘已经接通

旧设置由安装的 `ok/util/GlobalConfig.py:102` 注册，`custom_ok/ok/gui/MainWindow.py:110` 构造真实 NotificationManager。manager.submit → NotificationPipeline 的队列 → manager._send → 对应 provider / MessengerAutomation，构成真实消费者链；不是仅有默认配置。

| 旧设置组及其持久化字段 | 旧投递消费者 | 当前原生状态 |
| --- | --- | --- |
| System Notification | MainWindow / NotificationManager.system_enabled 与系统托盘展示 | **已迁移**：desktop_preferences 读取旧 Notification.json 的布尔值；GUI._notify 展示应用文字及 QSystemTrayIcon.showMessage。 |
| Discord Notification / Discord Webhook | DiscordProvider.send：webhook 请求，可附 PNG | **尚未迁移**：原生没有 Notification metadata 或 provider 投递链。 |
| Telegram Notification / Telegram Bot Token / Telegram Chat ID | TelegramBotProvider.send：sendMessage / sendPhoto | **尚未迁移**。 |
| Enterprise WeChat Webhook Notification / Enterprise WeChat Webhook URL | WeComWebhookProvider.send：markdown / image，并检查业务响应 | **尚未迁移**。 |
| QQ Bot API Notification / QQ Bot API App ID / QQ Bot API Token / QQ Bot API Channel ID | QQBotProvider.send：QQ Guild channel API；当前旧实现对 images 仅添加数量说明，没有上传图片 | **尚未迁移**；后续不得把旧实现描述为完整 QQ 图片投递。 |
| QQ Desktop Notification (Not Reliable) / QQ Desktop Nickname | manager._send 调用 MessengerAutomation，使用 QQ 窗口、OCR、联系人和图片菜单 | **尚未迁移**。旧版自己标注不可靠；有实际消费者，不应以“不可靠”为理由算已完成或不存在。 |
| WeChat Desktop Notification (Not Reliable) / WeChat Desktop Nickname | 对 WeChat/Weixin 窗口调用 MessengerAutomation | **尚未迁移**。 |

旧 manager 的渠道分支证据在 `.venv/Lib/site-packages/ok/notification/manager.py:60`，API 实现在同目录 `providers.py`，桌面操作实现在 `windows_messenger.py`（本产品另有 `custom_ok/ok/notification/windows_messenger.py` 覆盖）。原生 `native_combat_host.py:137` 当前保存诊断图片并发 `combat-notification` 事件；`gameframe/gui.py:438` 只显示文字/托盘。应用内提醒、图片保存、账号备注表单均不能替代外部投递。未发送消息验证任何渠道，也未读取真实凭证内容。

## 4. PyAppify / App Launcher：外部发行器设置不等同 native 更新

旧适配有三个真实控件：

| 旧控件 / 行为 | 可验证旧消费者 | 当前原生判断 |
| --- | --- | --- |
| Auto Start {app_name} | `GlobalConfig.AppLauncherConfig.__setitem__` → `update_app_config(auto_start=...)` → `pyappify/app_config.py:116` 原子更新发行器 app.json；旧帮助明确为 Windows 登录时启动 | **没有原生等价配置**。native 的“打开应用时恢复服务”和固定 once/daily/weekly 定时任务均不是登录时启动。PyAppify 配置适配本身不适用于没有该发行器的部署；是否要求原生登录自启动，仍需产品范围确认。未验证外部发行器二进制如何消费 app.json。 |
| Auto Update：Manual / Release Only / Pre-release | AppLauncherConfig 把显示选项转换为 MANUAL_UPDATE / AUTO_UPDATE / AUTO_UPDATE_PRE_RELEASE，写发行器 app.json | **没有等价自动更新策略**。native 有人工检查/下载/替换游戏包，但 `LanUpdateConfig.load` 只支持 stable；NativeGamePackUpdateCard 只绑定用户 action，没有 app-start 自动检查/安装或 prerelease 选择。原生更新路径已存在不等于三种旧策略全部迁移。 |
| Launcher / Open Launcher，以及旧关于页检查更新 | `create_app_launcher_options` 注入 show_pyappify 回调；VersionCard 只在发行器 app_version 存在时显示按钮 | **发行器专属入口不适用**。原生 Manage / Update Gamepack 是独立包管理入口；不能把 UI 文字相似当同一消费者。 |
| 首次显示 hide/kill、升级 PyAppify 自身、继承 app_version/app_profile、启动版本变更提示 | `custom_ok/ok/gui/MainWindow.py:629`；安装的 `ok/__init__.py:518`、`ok/gui/util/pyappify_startup.py` | **发行协议已更换**。native 以 manifest 和文件索引为权威，没有绑定 PyAppify 的来源路径；无需复制外部发行器专属环境变量、资源或 PID 清理。 |

旧适配自身也有外部输入边界：`create_app_launcher_options:317` 要求三个 callable API、存在的 app.json、布尔 auto_start 和受支持 update_method；API 不可用时不显示面板。不能因为本机安装了 pyappify 就认定原生发行包可以操作它。`NativeGamePackUpdateService` 的长度/SHA256/依赖/包身份核验和显式 owner 停机流程应保留，不为补旧策略而绕开。

## 5. 窗口相关剩余行为与无效字段

| 项目 | 证据及状态 |
| --- | --- |
| 启动前 GPU 后处理告警 | **尚未迁移**。安装的 `StartController.do_start:87` 在 start_exe 条件之外无条件调用 `check_gpu_driver_post_processing:198`；解析已选 exe/HWND，检测 NVIDIA Filter Profile、NVIDIA/AMD sharpening、RTX Dynamic Vibrance，以及 Windows HDR 状态下的 RTX HDR，向通知路径发告警。原生 plugin/Windows device/host 中没有该检测消费者。该旧路径即使手动启动游戏仍可到达。 |
| check_hdr / force_no_hdr / check_night_light / force_no_night_light | `config.py:211` 保留定义，但对检查范围内安装的 ok 与 custom_ok Python 全文搜索未发现读取；DeviceManager 传给 HwndWindow 的参数也不包含它们。**目前不能据这些字段推导“夜间模式检测/强关 HDR 已实现且需要迁移”**。上行真实 GPU 检测不由这些字段开关控制，也不执行强制关闭。 |
| WGC / BitBlt_RenderFull 捕获选项 | 旧 `config.py:207` 配置二者，安装的 `ok/device/capture_methods/update.py` 选择可用后端。原生 WindowsDevice 实际只有 WGC capture，DeviceEditor 没有 BitBlt 消费者；**旧 BitBlt 后端尚未迁移**，不能从当前 HWND 选择界面推导同样的捕获兼容性。 |
| PostMessage 后台输入语义 | 旧 config 指定 PostMessage，DeviceManager 映射到 PostMessageInteraction；原生 `_SendInput` / WindowsDevice 验证前台，否则拒绝送输入。**能力边界不同**；当前前台输入有实现，后台 PostMessage 语义没有等价实现。这里不建议添加不可执行的切换字段。 |
| GUI 位置、大小和最大化恢复 | `custom_ok/ok/gui/MainWindow.py:802` 从 ok_config 恢复 x/y/width/height/maximized，`:864` 监听 move/resize，`:871` 写回。原生 GameFrameWindow 仅 `resize(980,800)`，launcher options/context 没有 geometry 字段；**尚未迁移窗口状态持久化**。游戏 client 自动缩放是另一项消费者。 |
| 旧 Fluent 侧栏展开状态 | 旧 `MainWindow.py:830,861` 消费 navigation_expanded；当前 core 没有对应旧 Fluent 侧栏。**旧布局专属状态不适用**；不要为保留旧字段创建无消费者设置。 |
| 暗色 / 系统主题 | 魔改 SettingTab 已锁定 Theme.LIGHT，主题控件仅说明文字。**不构成恢复可切换暗色模式的已证实需求**。 |

## 6. 本轮结论与验证边界

当前可明确列为剩余真实迁移项的消费者是：六个外部通知渠道、UID 实时遮罩、启动前 GPU 后处理告警、旧 BitBlt/后台 PostMessage 能力，以及 GUI geometry 持久化。热键的无会话启动语义只迁移了一部分。PyAppify 的登录自启动与自动更新策略没有原生等价配置；外部发行器专属按钮和清理则不适用于当前包架构，应分开描述。

这是源码与契约覆盖清单，不是新实现计划，也不自动要求把所有旧发行器特性复制回来。原生代码已有的设置消费者与已完成离线测试仍不证明真实游戏、GPU/音频硬件、外部消息、Windows 登录触发或更新投递成功。没有新的独立需求证据时，不增加兼容层、开关、等待或兜底。报告没有修改代码、语言资源、版本或发布状态。
