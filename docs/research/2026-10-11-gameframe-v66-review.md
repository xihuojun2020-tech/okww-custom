# GameFrame v66 增量交叉审查与管理入口验收

本轮补齐了两个真实执行边界：后台任务暂停后应继续保留服务，以及全新安装必须能通过明确的管理操作建立可信账号配置。原生任务仍沿用生产账号选择、别名、掩码手机号、特征码核验、登录、退出和完整性服务。独立管理窗口复用原账号与完成证据控件，属于游戏包的 AGPL 管理扩展；Qt 与 ok-script 仅在该独立进程使用。

## 范围

基线为已发布 `v1.97.65`，提交 `5098fcdc`。检查当前 GameFrame API、worker、controller、launcher、原生 Host/Task/Executor、账号运行时、证据写入和安装载荷边界。使用仓库 `.venv`、临时账号目录、合成画面、Replay 和 Qt offscreen；未启动游戏、模拟器、真实捕获或输入，未执行账号登录、Child Session、系统设置修改或 NAS 操作。

## 已观察问题与修复

| 实际失败路径 | 证据 | 当前处理 |
|---|---|---|
| 后台服务暂停后退出 | 真实 TaskContext/NativeCombatExecutor probe 在首轮设置 pause，再恢复时 `polls=1`、stop 未设置、enabled 仍为 True。旧 catch 在等待恢复后发现 paused=False 而重新抛出 Cancelled | Host 的后台 catch 只在明确 stop 或非暂停取消时重抛，暂停留在服务循环。相应执行测试由 Host 负责人维护 |
| 原生诊断 PNG 泄露身份区域 | 对真实 Host.save_screenshot 与 NativeTask.screenshot 的合成 PNG 读回均显示身份区域未遮罩 | 共用 save_native_screenshot 复制输入后，按原生产 blur_area 几何黑色遮罩，保存于显式 data_dir/okww监控室；不修改输入原图。720p/1080p 与路径/编码失败检查通过 |
| CompletionEvidence 未绑定 executor | 独立实际 Host probe：singleton 已准备，但 executor_bound、daily_run_created、task_evidence_submitted 均为 False | Host 在已准备账号运行时存在时绑定同一根目录的服务，原 begin_daily_run/record_task_evidence 可使用原仓库。未准备的独立战斗 Host 不隐式读取默认账号目录 |
| 已停止的登录入口仍开始证据采样 | switch_to_account 进入时 stop 已设置，但旧入口先执行 transition guard、evidence、foreground read | 原生入口先 executor.check_enabled；真实 MultiAccountDailyTask regression 证明停止在任何 evidence/foreground 操作之前传播，Replay 零动作 |
| native config.update 静默跳过校验和持久化 | 原 Config 继承 dict.update，而任务覆盖配置需要原 validator、保存和界面变更事件 | 批量 incoming 先全部校验，再保存一次，成功保存后按 changed 项发送 on_change；拒绝批次不改内存或文件，磁盘失败不发成功事件，真实重载保留合法配置 |
| 全新安装被可信 master 预检阻断且无管理入口 | 所有任务先 require_ready；空目录没有账号 master，测试 fixture 无法代替用户初始化 | 新增 src.management 及 ManagementWindow：空目录保持安全模式，用户填写首账号→原 bundle 预检→确认→原事务导入；旧配置通过原完整性 controller 明确锚定，配置包通过原预览与确认导入 |

新增保护分支有具体合同：首账号初始化不能覆盖已有 master/working；导入必须依据原服务的预览与并发版本；管理进程没有 executor，因此实时截图和特征码控件明确不可用；PNG 路径必须留在约定监控目录。没有增加空 master、自动信任、默认成功或游戏启动兜底。

## 管理扩展的实际安装验收

`src.management.manage(data_dir, program_version)` 与 CLI `python -m src.management --data-dir ABS --version VERSION` 不读取项目根 config.py、main.py 或 custom_ok。原生包管理进程使用单独的 `requirements-management.txt`，锁定 ok-script 1.0.190、Qt 6.9.1、Fluent 1.8.3 及对应 Windows 依赖；原生 worker 的 requirements 保持独立。

实际测试执行 `build_native_gamepack` 和 `install_archive`，通过 SHA256 index 校验后，仅将安装目录的 payload 放入子进程 sys.path。确认 ZIP 没有 payload/config.py、main.py 或 custom_ok，并硬阻这些模块导入；真实管理服务从用户表单形状的合成首账号建立可信配置，再创建 AccountSettingsTab 和 CompletionCheckTab 两个页面。DeviceManager/TaskExecutor 构造被硬拒绝，窗口仍打开并输出 management-ready；stdin stop 经 queued Qt Signal 关闭，进程 exit 0。src.management 实际来源为安装后的 payload。

测试覆盖首账号 preview 不写 master、不确认拒绝、无效手机号拒绝、确认后真实事务发布与完整性检查、保留别名/手机号/特征码、关闭新账号乐园安排、后续原 AccountConfigEditor 创建、已有配置不可被首账号入口覆盖，以及导出配置包再导入空安装保留账号 UUID。上述使用合成账号，不操作任何真实账号。

## 检查结果

| 本轮检查 | 结果 | 限制 |
|---|---|---|
| TestNativeAccountRuntime + TestNativeScreenshots | 10 项通过，4.775 秒；账号运行时 8 项，截图 2 项 | 原生闭包不导入旧框架/Qt；OCR spy 验证接口与阈值，不能证明真实 OCR 准确率 |
| TestNativeConfig + 前四项 TestAccountManagementEntry | 5 项通过，2.731 秒 | 批量配置与原管理事务/Qt离屏入口；不连接游戏 |
| 新增实际安装 ZIP 管理入口项 | 1 项通过，4.538 秒 | 使用本机已安装的锁定依赖，不等同于在全新机器完成依赖安装 |
| 修改身份共用校验后的两项原 AccountConfigEditor 创建检查 + NativeConfig | 3 项通过 | 原模板/身份分离与槽位重复拒绝保持，未重复无变化的全部账号回归 |
| 历史七组旧账号回归 | 保留此前193项通过记录，本轮未重新运行 | 不将历史与新增数字累计冒充一个测试批次 |

## 尚未完成的边界

管理窗口当前明确提供账号/序列、原完整性检查、配置包导入导出、已有完成证据查看/打包与本地资料目录。实时读取特征码与捕获截图需要任务窗口。以下旧管理卡片还不能宣称完成迁移：DiagnosticStatusCard 默认根来自 diagnostic_policy.REPO，凭据、上传与系统调度器依赖旧安装位置；LanUpdateCard 的下载/安装请求硬编码 src 所在安装根，并以 main.py 重启；ToolsHubTab 与 GeneralSettingsTab 依赖旧 StartTab、OneTimeTaskTab、SettingTab、executor/global_config。入口没有自动运行这些功能。

诊断 PNG 遮罩不代表所有业务证据已遮罩：EvidenceRepository 保存完成证据、DailyTask 监控 VideoWriter 和 MaterialPlannerTask 的原画面保存仍有各自既有像素合同。本轮不据此改写原始完成证据或视频，也不声称所有保存路径已隐私处理。

本轮先发现的丢失游戏重启与 MouseReset 恢复问题已交由对应执行负责人处理；这份交叉审查不代替其实际 Windows/Replay 专项结果。任务生产路径能导入、能够构造29类、完成若干真实 Replay 分支，均不等同于全部29类真实游戏运行成功。最终发布版本、核心 launcher 管理子进程验收及新增业务专项由主代理汇总。
