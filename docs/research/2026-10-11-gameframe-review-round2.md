# GameFrame 第二轮独立审查

审查日期：2026-10-11。最终集成基线为已发布的 `v1.97.63`，本次发行版本 `1.97.64`；首次审查时工作目录为 1.97.61，下文保留首次与修复后验证的区别。本轮确认独立核心可以构建为 wheel，鸣潮兼容包可以构建为包含生产源码和素材的 ZIP，元数据检查不会启动游戏。离线回归已覆盖真实图片规则到 mock 输入、运行记录、错误释放、持续服务和生产停止桥。鸣潮包仍通过原应用执行；这不等于全部任务或角色已迁移到原生核心。

## 范围与验证边界

人工阅读 `gameframe/api.py`、`packages.py`、`state.py`、`runtime.py`、`vision.py`、`controller.py`、`worker.py`、`__main__.py`、`pyproject.toml`，以及设备实现、GUI、鸣潮 `plugin.py`/`bootstrap.py`、构建脚本和相关离线测试。停止路径定点核对 `main.run_application` 与生产 `TaskExecutor`；没有运行实际鸣潮任务。

没有启动游戏、模拟器、真实设备捕获或输入，没有实际账号切换、Child Session、系统设置修改或 NAS 操作。Windows 和 MuMu 的测试使用注入的假后端；生产应用测试通过 AST 提取实际函数及 mock 依赖执行。它们证明调用和状态契约，不能替代设备实测或完整应用运行。

## 本轮发现及修复

| 发现 | 原失败证据 | 当前处理及离线证据 |
|---|---|---|
| 配置合并异常遗留输入锁 | 旧 `Runtime.run` 在锁后、`try/finally` 前执行 `merged.update`；传入 `config=1` 抛 `TypeError`，下一次正常运行报输入被占用，锁仍 locked | 合并和 TaskContext 构造移到 acquire 前；`test_config_merge_failure_does_not_acquire_input_owner` 通过 |
| Controller 改 cwd 后误解相对 data_dir | native 子进程 cwd 是框架安装根，调用者相对数据目录原样转发 | Controller 在调用者目录 resolve data_dir；相对目录回归通过 |
| 兼容进程停止没有消费 stdin | 原 bootstrap 没有停止监听，Controller 只能超时 terminate；生产 cleanup 没有协作退出机会 | bootstrap 把 JSON stop 转为 Event；共用 `main.run_application(task, stop_event)` 调 `OK.quit`、唤醒 executor 并等待其清理；预置停止、构造期间停止、执行器释放/销毁回归通过 |
| Windows 捕获与点击原点不一致 | WGC 保留窗口帧；mouse click 使用 client 坐标，带标题栏时视觉点产生偏移 | 帧按真实 DWM bounds、client rect 和 client origin 裁剪；几何在临时线程 DPI context 中读取；帧尺寸/区域不匹配明确报错，client 裁剪及点击回归通过 |
| Windows 依赖范围允许缺失 HWND API 的发行版 | 公开 `windows-capture` 1.5.0 wheel 的 Python 构造函数无 `window_hwnd`；2.0.1 有该参数 | windows extra 固定 `windows-capture==2.0.1`；未在真实 HWND 上验证 |
| legacy 控制监听线程异常后任务继续执行 | bootstrap 原先直接 JSON decode，畸形 JSON、缺 command 和未知命令没有有效停止结果 | 与 native worker 共用控制语义：输出 control-failed 并设置生产 stop_event；五种畸形/未知消息回归通过 |

路径复核：Controller 除了 resolve data_dir，现已保留 native worker 的调用者 cwd，并通过 PYTHONPATH 提供源码模式的核心导入根。因此 replay frames 和规则 template 的相对路径仍以调用者目录解释；新增隔离 cwd 的真实子进程回归通过，不需要猜测并逐字段重写游戏配置路径。

Windows 的裁剪契约要求收到的 WGC 帧尺寸与物理 DWM extended bounds 相符；当前实现不把这一条件当作微软对所有窗口和系统版本的保证。不同游戏模式、窗口 resize 和 DPI 场景仍待获授权后实测。CPU client 裁剪也不等于 GPU ROI 抓图。

另发现 WGC 已结束 control 的复用问题：若捕获线程已关闭或 callback 抛错，继续保留 `_capture` 会使持续服务重复访问结束的 control。公开 2.0.1 sdist 的 NativeCaptureControl 在 wait/stop 中 `capture_control.take()` 消费内部对象，join 错误变为 Python exception；消费后 is_finished=True，再次 wait/stop 无动作。现已在确认结束时 join 一次报告真实错误，并在 finally 清除旧 capture/control/帧，下次调用重建；新增失败后重建回归通过。没有增加盲目等待或第二套重试机制。

## 执行、能力与成功语义

`Runtime.run` 在开始运行前检查所需 device capabilities，并以单个锁控制输入。Replay 提供帧、键盘、鼠标、相对鼠标及 multitouch；Windows 提供帧/键盘/鼠标/相对鼠标；MuMu 提供帧和 multitouch。需要 mouse 的通用 probe 在 MuMu 上被拒绝符合契约，不能把能力拒绝改成假支持。ADB 离线截图及离散输入契约已测试，持续按键与同时多点不在其能力声明中。

native 运行的普通异常与抓图失败写入 failed，显式停止写 cancelled；设备释放失败也阻止 success。`run_service` 保留持久 enabled 意图并在错误后等待，global pause 和 stop 只影响执行。设备能力声明通过不证明一个游戏算法适合 Android/MuMu；鸣潮兼容包继续采用生产设备选择。

`Runtime.run` 每次调用一次 `release_all`，worker 的最后 `close` 在设备层也可调用释放。第二次对空 held 集合不会重新发送已经释放的键；若第一次真实释放失败，关闭时再次释放有实际恢复依据。这是分层清理，不应为了“调用次数一次”删除关闭安全动作。

GUI 对子进程输出显示退出码，没有把 code 0 命名为游戏业务完成。legacy 过程不向 GameFrame 的 native 运行表写业务 success。native 包返回 mapping 未声明 status 时按 API 约定使用 success；业务完成检查应由包返回具体结果或 blocked/skipped，不能由框架替游戏推断。

## 安装、wheel 和鸣潮 ZIP

core wheel 在临时源码副本通过本地 venv 的 `pip wheel --no-deps --no-cache-dir` 构建，包含核心、devices、GUI 文件、MIT LICENSE 与 console entrypoint；从临时工作目录以隔离 Python 导入 api/packages/runtime/controller/worker 成功。这是发行结构检查，使用了当前 venv 的已安装依赖，没有在全新 Python 环境安装依赖验证。源码仍在变更，本轮临时 wheel 不作为最终发行物。

包入口 resolve 到 manifest 根内；重复 task、未知 API 和非法 entrypoint 拒绝。新增 ZIP 安装 CLI 使用临时目录、拒绝路径越界/符号链接/重复成员，核对可选 SHA256 文件表，目标包存在时不覆盖；安装回归覆盖正常安装、内容损坏与越界后无部分安装。普通 ZIP 解包和源码加载仍是执行用户选择的 Python 包，SHA256 表用于完整性检查，不代表来源签名。

鸣潮源包有 30 个入口：application、22 个一次任务、7 个触发任务；manifest 列出 57 个角色源码文件。`create_package` 只读 metadata。bootstrap 在首次 import main 前设置生产 argv，然后共用生产初始化和确切任务类入口；账号预检、存储、hooks 不另写第二套。

构建 ZIP 自带 `payload` 中生产 src/custom_ok、资源、翻译、requirements、AGPL 许可及素材来源表，包含每文件 SHA256，固定 ZIP 时间。它不含账号 configs、logs、venv、cache 或供应商 DLL，不覆盖已有输出。解包后的命令只引用包内 payload，不依赖开发仓库。src 下的新 framework overlay 文件会由现有源码枚举纳入，无需另设打包分支。

这个发行物是源码自包含兼容包，仍需要匹配 Python 与固定依赖，并未内置 Python/native runtime。data_dir 管理 GameFrame 的运行记录；旧鸣潮配置仍属其生产安装目录。单项 metadata 明示 `config_scope=production-installation`，不会把空 default_config 伪装成完整账号/战斗配置编辑。

## 可复验命令

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestGameFrameCore tests.TestGameFrameDevices tests.TestGameFrameMigration tests.TestGameFrameWorker tests.TestFrameworkErrorBoundaries -v
```

本轮首次执行 54 项通过：Core 18、Devices 10、Migration 5、Worker 7、ErrorBoundaries 14。随后 Controller 相对路径和生产 overlay 的变更另行复验，数字记录在本节后续补充，首次结果不代表新增代码已验证。

overlay 和 caller cwd 变更后，Migration 5、Worker 8、ErrorBoundaries 13 共 26 项通过。加入控制失败和纯颜色边界后，`TestPackColorVision` 4 项与 Migration 6 项共 10 项通过；三张现有战斗截图的 mask 像素和 crop 占比与旧生产函数一致，隔离子进程禁用 ok/gameframe 模块后仍能运行新颜色工具。生产 `TestGameRuntimeErrors`、`TestBaseCombatTask`、`TestAutoCombatRecovery` 共 52 项也通过，导入前将 Config.config_folder 设为临时目录并安装生产 overlay，没有使用真实账号配置。

合入 v1.97.63 后再次执行 Color 4 + Migration 6 共 10 项，通过并明确核对新版 manifest、57 个角色文件（含 TrialGenericChar）、overlay 和纯颜色工具进入 payload。生产回归加入 `TestCharacterIdentityRecovery`，四组共 76 项通过，包含既有 unknown generic 身份恢复，未回滚 1.97.62/63 修复。Devices 12 + Worker 9 共 21 项通过，新增覆盖 finished WGC 重建、命名战斗键、未响应的自有 worker 及其子进程清理，同时保留无关进程。最终 wheel/发行 ZIP 的哈希由发布步骤生成，本轮临时构建哈希不作为最终版本哈希。

## 后续迁移决策

兼容入口启动时对共享 site-packages 的写入现已移除，生产共用 `src.runtime.framework_overlay.install_framework_overlay` 精确查找补丁模块，其他模块仍由固定 ok-script 发行包加载。custom_ok/ok 没有 `__init__.py`，单纯把 custom_ok 加入 sys.path 不能覆盖已安装的 regular package。主入口在 prepare_storage 和首次 ok import 前安装 finder；同根重复安装幂等，已 import ok 或不同根补丁明确拒绝，不假装已覆盖。构建回归明确断言该 helper 进入 ZIP payload。

下一步按真实 ok 模块/API 矩阵确认战斗原生边界：TaskContext 已有设备、停止、时间和事件，但生产 BaseTask/ExecutorOperation、FeatureSet/OCR、Config/global services、scene 和 rotation 仍须逐项核对。角色/任务注册数量只能证明包完整枚举，不能当作功能完成。

已完成的窄迁移是 `src/vision/color.py` 五个纯颜色工具，业务和八个角色仅调整导入，算法、颜色阈值与区域语义保持。该 AGPL 包内模块无需旧 ok 或新 GameFrame，随 payload 的 src 收录；没有把来自旧框架的实现换成 MIT 许可。完整 153 符号归属和 native battle loop 的具体缺口见 `2026-10-11-gameframe-native-combat-boundary.md` / `2026-10-11-gameframe-api-matrix.json`。没有登记未实现的 native-combat。

## 外部依据

- [windows-capture 2.0.1 发行页](https://pypi.org/project/windows-capture/2.0.1/)；公开 wheel 正文核对另见 `2026-10-10-framework-followup-sources.md`。
- [微软 GetWindowRect 文档](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowrect)：可能含不可见 resize border，受 DPI 虚拟化。
- [微软 DWM window attributes 文档](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute)：extended frame bounds 为屏幕 RECT。
- [windows-capture window.rs](https://github.com/NiiightmareXD/windows-capture/blob/c7d106448eb9d9b251345c39047711e1cd408ae2/src/window.rs)：标题区域计算使用 DWM extended bounds 和 client rect，不是固定标题栏高度。
