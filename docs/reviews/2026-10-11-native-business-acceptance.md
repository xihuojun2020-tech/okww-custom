# 原生业务路径离线验收（2026-10-11）

本报告范围是 `TestNativeBusinessTasks.py`、原生 task/executor API 及 Windows 平台契约。全部使用仓库 `.venv\Scripts\python.exe -I`，显式插入仓库路径；禁止导入 ok、Qt、qfluentwidgets 和执行 config.py。未启动游戏、模拟器或访问 NAS。

账号主配置通过 `tests.fixture_support.make_account_environment` 生成，仅含合成 A1/A3/A4；随后执行真实 `prepare_native_account_runtime`。账号配置、材料库、截图证据和 OCR 编译缓存均位于测试临时目录。业务视觉使用本地 ONNXPaddleOcr/OpenVINO 和真实 fixture；只有账号切换入口专项使用原始 OCR 引擎的合成登录文本。

## 已验证路径

| 范围 | 执行证据 | 验证界限 |
| --- | --- | --- |
| 完整注册表 | `source_metadata` 读取 config.py AST；真实构造全部 29 个类，执行原 `after_init/on_create`，共享同一 executor/registry，配置目录为临时 root/configs | 构造成功不等于全部任务已完整运行 |
| CharacterTrial | 真实页面/按钮 OCR；真实 Host before_run → 原 run → 按配置扫描五个角色 → 原头像栏拖拽；Replay 首次业务鼠标按下后停止，Runtime 释放输入 | 未完成角色试用战斗和领奖 |
| EchoesRemain | 真实关卡 OCR、待完成状态判定 → 原 run/_navigate → 单人挑战按钮投递；首业务按下后停止，Runtime 释放输入 | 未完成编队、战斗或活动完结 |
| TiangongTreasure | 真实页面分数 30415/0 和编队页识别；原 run 读取关卡 → 选择待完成关卡，首业务按下后停止 | 未执行战斗和六关结果确认 |
| WeeklyBoss | 原 `_read_remaining` 稳定识别多个真实帧，结果为三次；未产生输入 | 未完整进入/挑战/领奖 |
| SeaRuins/Abyss | cwd 位于临时 data；原 Sea `_detail(...,7)` 识别通过，原角色 descriptor 构建读取绝对 coco 路径；Abyss 原 descriptor 构建、绯雪模板及四张状态模板存在并读取成功 | 未验证整场挑战 |
| EchoesRemain 证据 | 原 `_save_proof` 写入临时 root；JSON 配套证据存在，图像上下 2.5% 遮罩，原输入 frame 未被修改 | 本地证据，不表示活动完成 |
| MaterialPlanner | 真实 repository.root 为同一临时 root/MaterialPlanner | 未执行培养规划资源消费 |
| TestAccountSwitch | 真实 TestAccountSwitch.run、原 MultiAccountDailyTask `_select_and_login_specific`、原 `switch_to_account`、原 LoginFlowService `switch_to_account` 依次进入；只读 profile observer 在最终入口设置停止，真实异常传播与取消清理 | 仅共享生产链入口/取消；未宣称完整选号、退登、登录或 A1→A3→A4 切换成功 |

以上业务文件共 11 项检查，分组执行通过。前三个完整 run 入口检查在 Runtime 单输入 owner 下执行，首次业务输入后设置 stop，不用替换业务方法制造成功。

## 已修复的迁移根因

1. NativeBaseTask 的 `_ocr` 实例属性覆盖 CharacterTrialTask/WeeklyBossTask 的同名业务方法。内部服务改名 `_ocr_service`，真实 CharacterTrial 页面及 Weekly 稳定次数分支覆盖修复。
2. NativeExecutor 的 `click(move=False)` 丢弃明确坐标。旧 PostMessage 即使 move=False 仍向指定点发消息，旧 pynput 也移动到指定点。原生 foreground 输入现保留该坐标；CharacterTrial 与 Echoes 的真实按钮投递检查覆盖修复。
3. 生产灰色确认按钮点击使用 move_back=True。现通过真实 `assets/images/33.png` 识别按钮，点击后恢复原 cursor，按下期间 stop 也在 finally 恢复；Replay 提供明确 cursor 状态。
4. 身份核验调用 `executor.ocr_lib('default')`。原生 accessor 返回显式配置的引擎；实际 `read_code` 私有裁剪、放大与解析专项通过。
5. 暂停确认必须发生在输入 owner 释放持有输入之后。pause/unpause 使用 context.observe_pause；真实 W held → pause 释放一次 → resume E → stop 取消专项通过。

## Windows 平台离线契约

WindowsDevice 的 window adapter 使用真实 Win32 查询与物理 DPI 坐标，提供选定 HWND 的 exists/title、foreground visible、同 PID 登录窗口快照、top HWND 和 capture origin；foreground 查询不会激活窗口。cursor、hotkey 与 foreground PID 都有可注入 mock 边界。

`stop_target` 只处理选定且仍属于可信 PID 的 live HWND，创建 psutil.Process 身份后再次核对 HWND/PID，终止该单一进程并 wait 确认；不按名称批量终止。全部验收使用 mock backend/process，未执行真实终止操作。Replay 明确记录模拟 stop_target。

refresh_target 验证既有 HWND 的 PID 与进程创建时间，或显式绑定可信原进程的唯一可见替代窗口。start_target 仅使用配置的绝对 launch_command 与 target_executable，跟踪启动器及已观察子进程，不全局扫描。重新绑定停止并等待旧 WGC，清除旧帧，保留同一 window adapter，重新启动捕获。TestWindowsLaunch 共 12 项 mock 检查通过，覆盖子进程存活、身份复用、歧义、取消、未记录进程族的启动器提前退出。hwnd 可省略或为 0，但必须提供完整显式启动配置；prepare(stop) 在首次启动后创建已绑定有效 HWND 的 adapter，提前取消不会启动进程。实际 MultiAccountDailyTask._restart_game_once 经真实 refresh/start_device/start_capture 路径绑定新 HWND，再传播捕获后取消；未启动真实进程。

## 强制停止的设备进程所有权

Controller 每次启动生成随机本地保护登记文件，通过环境变量交给设备。WindowsDevice 显式启动命令后立即登记启动器 PID/创建时间，并登记实际观察的子进程；写入采用原子替换。强制停止仅排除创建时间仍匹配的登记进程及当前后代，继续清理执行树中的 venv redirector、Python worker 和未保护子进程，close 后删除文件。TestProcessOwnership 2 项通过，覆盖实际设备 mock 登记、重复登记、PID 复用和后代消失；TestGameFrameWorker 14 项通过，其中真实本地 Python fixture 证明设备登记的 Python 游戏及其后代保持运行，无响应执行子进程退出。仅测试创建的 fixture 进程被清理，未操作真实游戏。

## 追加复核

账号切换入口专项已移除禁用 MouseReset 的配置绕过，使用默认设置再次通过。LoginFlowService 原生入口先检查停止，取消沿生产链传播；该结果仍仅覆盖入口与清理。SessionPreempted 采用 BaseException 控制流，专项确认业务 except Exception 不会误吞；多服务会话调度由主任务的 Host 验收单独覆盖。

没有充分证据将本次离线结果称为 Windows 实机运行、完整账号切换、完整资源消费或全部 29 个任务功能成功。已有 legacy 账号算法回归与这里的原生入口验收是不同证据范围。
