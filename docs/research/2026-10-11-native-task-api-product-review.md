# 原生任务 API 与产品入口复核

复核时间：2026-10-11。范围为 `gamepacks/wuthering_waves_native/manifest.json` 的 29 个生产任务、其实际父类、原生 Host/Executor/Config 与现有管理入口。未运行真实游戏、读取真实账号或 NAS；不重复此前通过的完整测试。本报告不涵盖诊断上传、监控和更新工具。

当前生产任务已接入原生调用链，但任务配置界面、全局配置编辑、自定义任务热载、角色编辑和日历定时入口仍未完成迁移。已发现并经主任务授权修复两项确定的运行问题：Solo 手动切换继承合同、执行起始时间。最后补齐了 stdin 请求在配置修改之前的合同校验。

## 本轮确定问题与修复

1. **Solo 开启和关闭失效。** 原 Host 按类名仅处理 AutoCombatTask，SoloCombatTask 继承的 `on_create/enable/disable` 同样依赖 `_manual_desired`，普通 `disable` 刻意保留用户意图。已改为生产 AutoCombatTask 的 `isinstance`。临时配置中默认关闭 → 真正开启 → 原始 Solo poll 读取菜单 → 关闭，分别重载 Config 验证启用和禁用落盘，专项通过。证据：`src/runtime/native_combat_host.py::_set_service`、`src/task/AutoCombatTask.py:50/68/89`、`src/task/SoloCombatTask.py:4`。
2. **声骸效率趋近零。** `NativeBaseTask.start_time` 初始化为 0，原 Host 未在执行开始赋值；生产 `BaseWWTask.incr_drop` 用该值计算每小时声骸数。旧 `ok/task/TaskExecutor.py:675` 在区分 trigger/once 前每次执行设置 `time.time()`，现 Host 的 run_once 和 poll 保持相同行为。真实 AutoPick 菜单 poll 后调用生产 incr_drop，以及前台生命周期时间范围，两项专项通过。证据：`src/runtime/native_task.py:87`、`src/task/BaseWWTask.py:1267`。
3. **非法请求先改配置后报错。** Host 现先验证命令、任务种类、config 对象、enabled 布尔值和设备能力，再改 Config。`enabled=0` 附带 `_enabled=False`、一次性任务请求 set-service 附带 Exit After Task=True 的专项验证内存、重载文件均不变，服务继续启用，未发送输入。

## 29 个任务的实际调用边界

以下按实际 run 路径归类，不把静态注册等同于所有游戏分支运行成功。

| 任务（29 项） | 实际复用的调用面 | 复核结果 |
|---|---|---|
| DailyTask、MultiAccountDailyTask、MultiAccountWeeklyGardenTask | 原始 before/run/after 生命周期、账号选择/身份核验、registry 子任务、OCR、设备 refresh/start/capture、完成证据与耗时记录 | 生产逻辑仍复用；管理窗口没有执行设备，读取特征码仍禁用 |
| FarmEchoTask、WorldBossMaterialTask、NightmareNestTask、TacetTask、ForgeryTask、SimulationTask、WeeklyBossTask | 书页/导航、OCR/feature、输入、共同 combat loop、奖励/体力账本、真实 YOLO | 原生父类提供调用面；实际游戏奖励与所有导航正路径不在本轮验证范围 |
| MaterialPlannerTask | 已验证 Daily 调用 run_for_profile、OCR/截图、材料持久仓库 | `visible=False`，其直接 run 明确报错；manifest/launcher 仍将它作为可选任务显示，需过滤隐藏依赖 |
| GardenTask、EventTask、AutoAbyssTask、AutoSeaRuinsTask、EchoesRemainTask、CharacterTrialTask、TiangongTreasureTask | 原生产页面状态、挑战输入、OCR/feature、共享 registry/combat、各自周期/奖励记录 | 保留业务调用路径；静态调用扫描中的 callback/mixin 字段不构成缺失 API 证据 |
| TestAccountSwitchTask、PianoTeachingTask、SecondSolTask、ResonanceSimulationTask | 真实生产账号切换、前台生命周期、按键释放、foreground/PID/hotkey 查询 | 设备边界已显式提供；TestAccountSwitch finally 恢复 MouseReset 不再因 unsupported 覆盖结果 |
| AutoCombatTask、SoloCombatTask、AutoPickTask、AutoLoginTask、AutoDialogTask、FastTravelTask、MouseResetTask | 原 should_trigger/run、保存 enabled、原错误恢复、同线程 session；MouseReset 直接设备 cursor 与 client_to_screen | 服务与 once 共享执行者；MouseReset 原生同步轮询取代 legacy handler，不创建第二输入线程 |

未发现需要为了这些 run 路径增加假 ok 模块、静默 no-op 或额外兼容层的依据。`BaseWWTask.test_absorb` 对 ocr_lib 的旧调用本身与当前旧库签名不符，但它不是注册任务的 run 调用链，不能据此扩展原生 API。

## 配置与生命周期语义

- `NativeBaseTask.validate_config` 默认返回 None，与旧 BaseTask 的空方法语义一致；`validate`、load_config、on_create，以及 TriggerTask 从 `_enabled` 恢复意图，都遵循原 API。Piano、CharacterTrial、Daily、MultiAccount 的生产 validator 仍由真实子类提供。没有独立证据要求再加通用数值或类型校验。
- Native Config 的 setitem/update 调用生产 validator；update 在验证后保存一次并逐键通知 on_change，after_init 的外部 override 走 update。Daily/MultiAccount 的 on_change 在原 after_init 后接入。Native 保存失败明确抛出，与旧 Config.save_file 仅日志并吞失败有差异；这是可见失败，不是假成功。
- Daily 的 validator 带切换方案副作用，不能改成“纯类型检查”而丢弃 `_do_switch_profile`。跨多个键的 UI 编辑需要保留这一生产行为；本轮没有认定其存在新的失败路径。
- registry 子任务的 run_task_by_class 复用原信息共享；当前 Native 增加 finally 恢复信息，保持前台任务为 input owner。未要求为每个依赖任务启用独立执行者。

## SessionPreempted 与清理

`SessionPreempted(BaseException)` 专用于后台轮询察觉请求；Host 在 poll 期间安装 checkpoint，在 finally 清除、release_all 并恢复当前任务。一次性任务期间不安装抢占钩子。生产战斗的 `except Exception` 重试不会将该控制流误报为普通错误。

实际释放函数 `send_key_up/mouse_up` 不调用 check_enabled，所以抢占不阻断按键松开。BaseChar 的 heavy-click finally、BaseCombat 的 combat_once finally、AutoCombat 的 run finally 仍执行。`finish_rotation_tracking` 只弹出状态、快照和写日志，不读新截图或检查 checkpoint，不会把原任务异常替换成新的抢占。真实 rotation → perform → do_perform 首次 down 后请求关闭和前台任务的已过回归证明释放后继续消费队列。

真实业务错误进入 BaseCombat 的恢复分支时先 record_combat_error，再等待；等待阶段抢占不会删除已经记录的根因。未发现这些生产路径捕获 BaseException 后伪造成功。底层 release_all 本身失败仍可能令清理异常覆盖正在退出的控制流，本轮未观察到这一故障，也未新增假恢复分支。

## 下一批必须补的产品能力

| 能力 | 现状与源码证据 | 必要补项 |
|---|---|---|
| 全任务配置界面 | `gameframe/gui.py:133` 只显示 launcher.json 或 manifest default_config；大量 manifest default_config 是空对象。原任务的 config_type、description、动态 options、按钮、隐藏字段未传出 worker | 从独立 worker 导出真实任务 metadata/当前配置；按生产 schema 显示，保存交给 owner 请求。同步动态账号/序列选项，过滤 MaterialPlanner 等隐藏依赖 |
| 全局配置 | Host 仅创建 Game Hotkey、Character Config、Monthly Card Config 三组 Config；任务确实读取它们。`ManagementWindow.py:81/83` 仅挂账号与证据页 | 增加这三组的真实编辑/保存与运行中安全更新；保留月卡时刻、游戏热键和角色选项的生产说明。备份/仓库管理与执行设置分开接既有服务 |
| 自定义任务热载 | Host 只加载 manifest 的 module:Class；原 `ok/gui/tasks/TaskManger.py:94` 的 reload_task_code/custom_tasks 不在 native worker 调用链 | 提供 native 用户任务注册、保存和安全执行边界热载；不能假注册旧 ok 类或继续宣传当前支持旧脚本的全部 API |
| 角色编辑 | CustomCharLoader 的路径已跟 Config.config_folder；CharFactory:200/254 会加载文件及重新识别时替换类。管理窗口没挂 CharacterCodeTab，原 live reload 依赖旧 executor 列表 | 接角色编辑界面，并把安全替换请求交给 owner；现有文件加载可复用。用户旧脚本若直接 import ok，不能宣称已自动迁移 |
| 周期定时与耗时 | DailyTiming 及游戏日/周账本仍保留；support_schedule_task 的原业务标志存在，但 native launcher 无日历定时入口，旧 Windows scheduler 仍在 ok 模块 | 将支持的定时任务映射到稳定 task_id 的 session/worker 请求；恢复任务耗时/周期进度展示，勿把后台 trigger_interval 当成日历定时 |
| 后台轮询精度 | Host 每轮固定 sleep(.1)，MouseReset 原生 trigger_interval=.05，因此空闲期上限约 10Hz，而原鼠标防漂移目标是 20Hz | 调度等待应按真实 enabled 服务的下一到期时间计算；沿用现有生产间隔，不额外新增 retry/fallback |

本轮随后修复了全局暂停期间服务开关未落盘的问题：Host owner 在线程内 observe_pause，仍消费并保存 set-service，不调用 enable/capture 或发送游戏输入；前台请求保留到恢复。收到 stop 后先保存 listener 已按顺序入队的有效开关，再退出。启用时的实际初始化延迟到恢复，退出不会清除已保存的启用意图。三个专项覆盖真实 stdin listener 的 pause→disable→stop、暂停开启且不 capture/input、排队前台任务恢复后完成原生命周期，均通过。

本轮新增专项：Solo 保存/实际 poll 1 项，执行开始时间 2 项，非法请求不修改配置 1 项，暂停开关/恢复 3 项，均通过。此前完整原生 17 项、Host/Executor 30 项和传统路径 82 项结果由对应验证记录保留；这些数字不代表真实游戏全分支完成。
