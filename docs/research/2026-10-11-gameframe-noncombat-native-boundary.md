# 鸣潮其余任务原生迁移边界（2026-10-11）

当前自动战斗的独立运行已验收，其余任务不能据此直接登记为原生支持。本轮覆盖生产 config 中全部 22 个一次任务和 AutoCombat 之外的 6 个后台服务：28 个独立进程中，只有 `MaterialPlannerTask` 和 `SoloCombatTask` 完成禁止旧依赖的真实导入；其余 26 个在实际旧依赖处中止。导入成功也不证明任务执行成功。

这是只读调查，没有创建任务实例、启动 OK 应用/游戏/设备、登录账号、读私人配置或修改业务代码。调查发生于本轮通用平台迁移开始前，下表是这一时点的证据，后续修复应按真实变化更新。

## 真实导入与静态闭包怎样区分

从 `scripts.build_gamepack.source_metadata` 读取真实注册表。每个任务独立启动项目 `.venv` Python 的 `-I -B` 进程，cwd/Config root 都在临时目录；先 `combat_api.configure(native=True, data_dir=...)`，再用 import finder 禁止 `ok`、PySide6/PyQt、qfluentwidgets、custom_ok、config、main，最后只 import 生产模块。未伪造旧模块或任务方法。

另用 AST 枚举 src 中每个模块的 Import/ImportFrom 及函数内延迟依赖，追到所有包内可解析模块。全函数候选闭包包含 BaseWWTask.after_run → DailyTask → MultiAccountDailyTask/GUI，因此大多数任务的保守闭包为 176–185 个 src 模块；这不是运行时会同时导入的模块数量。`if __name__ == '__main__'` 下的 config/run_task 属于手动脚本入口，不计为常规生产导入故障。下表记录独立进程真正遇到的第一个阻点，后续列出源码中已确认的关键业务边界。

| 类（真实注册名） | 独立导入结果／第一个阻点 | 已观察到的下一层边界 |
|---|---|---|
| DailyTask | DailyTask.py:9 → daily_timing.py:9 `ok` | 顶层 Qt；安装目录账号 root；多子任务调用、完成证据、GUI refresh |
| FarmEchoTask | FarmEchoTask.py:8 `ok` | WWOneTime；input_text、scroll_relative、退出后配置 |
| WorldBossMaterialTask | WorldBossMaterialTask.py:6 `ok` | FarmEcho/WeeklyBoss；账号 quota journal；back |
| NightmareNestTask | NightmareNestTask.py:7 `ok` | WWOneTime；scroll_relative/back；Daily子入口 |
| TacetTask | TacetTask.py:4 `ok` | WWOneTime；scroll_relative/back |
| ForgeryTask | ForgeryTask.py:3 `ok` | DomainTask；颜色矩形、quota journal、back |
| MaterialPlannerTask | 导入成功，24 个 src 模块 | run 中 scroll_relative；run_for_profile 延迟 Forgery/Tacet 与任务 registry |
| SimulationTask | SimulationTask.py:3 `ok` | DomainTask → WWOneTime；导航/资源消耗合同 |
| MultiAccountDailyTask | MultiAccountDailyTask.py:24 → daily_timing.py:9 `ok` | Daily；原 LoginFlowService、Win32登录、账号 root、序列、GUI refresh |
| MultiAccountWeeklyGardenTask | MultiAccountWeeklyGardenTask.py:3 `ok` | Daily/MultiAccount与同一登录/序列/周记录 |
| GardenTask | GardenTask.py:7 `ok` | WWOneTime；每日/独立周乐园模式与完成记录 |
| EventTask | EventTask.py:9 `qfluentwidgets` | FluentIcon 配置按钮；WWOneTime 与活动判断 |
| TestAccountSwitchTask | TestAccountSwitchTask.py:12 `qfluentwidgets` | 原 MultiAccount 登录方法、repository、A1/A3/A4 精确短名与别名/掩码手机 |
| AutoAbyssTask | AutoAbyssTask.py:26 → WWOneTimeTask.py:1 `ok` | ensure_in_front、scroll_relative、swipe_relative；账号能量/赛季记录 |
| AutoSeaRuinsTask | AutoSeaRuinsTask.py:6 `ok.feature.FeatureSet` | 额外 FeatureSet；swipe/scroll；错误后人工 pause/继续 |
| WeeklyBossTask | WeeklyBossTask.py:5 `ok` | WWOneTime；scroll_relative；账号目标/奖励消耗 journal |
| PianoTeachingTask | PianoTeachingTask.py:4 `ok` | WWOneTime；键盘节奏执行和取消 |
| SecondSolTask | SecondSolTask.py:6 `ok` | 真实 Win32 foreground/window；interaction 短按 F 与 finally释放 |
| EchoesRemainTask | EchoesRemainTask.py:7 `ok` | WWOneTime；scroll；延迟旧 Screenshot 诊断与完成证据 |
| ResonanceSimulationTask | ResonanceSimulationTask.py:12 `ok.PostMessageInteraction` | 前台/热键监听与其自有技能循环；不能误登记为三角色生产循环 |
| CharacterTrialTask | CharacterTrialTask.py:5 `ok` | WWOneTime；scroll/swipe；当前账号身份验证 |
| TiangongTreasureTask | TiangongTreasureTask.py:4 `ok` | WWOneTime；试用队伍/挑战阶段及当前账号验证 |
| SoloCombatTask | 导入成功，86 个 src 模块 | AutoCombat子类；host须选择真实类，保留一人队伍条件、默认disabled |
| AutoPickTask | AutoPickTask.py:3 `ok.FindFeature/Logger` | TriggerTask/BaseWW混合MRO；OCR/拾取；不能与前台任务并行发键 |
| AutoLoginTask | AutoLoginTask.py:2 `ok.TriggerTask/Logger` | wait_login/trigger_navigation；客户端重启与窗口身份 |
| AutoDialogTask（模块 SkipDialogTask） | SkipDialogTask.py:3 `ok` | SkipBaseTask；trigger_navigation与对话取消/停顿 |
| FastTravelTask | FastTravelTask.py:2 `ok.TriggerTask/Logger` | trigger_navigation/传送确认；页面后验 |
| MouseResetTask | MouseResetTask.py:5 `ok.TriggerTask/Logger` | handler.post、Win32 Get/SetCursorPos、旧 capture 绝对坐标与窗口可见性 |

## 原生任务/执行器真正缺少的合同

对照已安装旧 `ok/task/task.py` 与当前 `native_task.py`，再检查实际业务调用。仅列有源码使用依据的缺口；不因旧框架存在某个 API 就要求复制它。

| 缺口 | 真实调用证据 | 最小实施边界 |
|---|---|---|
| scroll_relative | MaterialPlannerTask.py:112/149；DailyTask.py:567/2489；WeeklyBossTask.py:141；挑战等 | 映射当前设备的真实 scroll capability 和坐标，不模拟成功 |
| back | BaseWWTask.py:788 等；DomainTask.py:92；GardenTask.py:103 | 复用按键/现有导航合同 |
| input_text | FarmEchoTask.py:535；BaseCombatTask.py:469 | 复用实际 text 输入；登录路径已有精确 SendInput，不能改写切号算法 |
| ensure_in_front / swipe_relative | AutoAbyssTask.py:1822/1957 | 真实窗口/设备能力；保持前台输入要求 |
| swipe | BaseWWTask.py:173 延迟 import旧PostMessage，再调用 super().swipe；CharacterTrialTask.py:224 | 现 NativeTask父类无 swipe；需设备实现与原 PostMessage 路径显式区分 |
| run_task_by_class / task registry | DailyTask.py:486/2143；MultiAccountDailyTask.py:2192；farming_task_scheduler调用多个注册实例 | 在同一 executor/current_task/input owner内复用真实子任务实例及完成合同，不能每个子任务另开输入 worker |
| executor.get_task_by_class | WWOneTimeTask.py:11；LoginFlowService.py:27；现 executor无此方法 | 与 NativeTask的 tasks_by_class使用同一registry |
| pause/继续 | sea_ruins_recovery.py:52 | 停止仍有效、held输入先释放、保留foreground owner；不能将暂停当服务disable |
| add_exit_after_config | FarmEchoTask.py:70；MultiAccountDailyTask.py:170 | 只迁移真实退出行为与配置，不能复制旧GUI方法作空实现 |
| handler.post / cursor reset | MouseResetTask.py:32 | 该服务真实修改系统光标，依赖窗口/capture；不能以无操作替身声称迁移完成 |

`calculate_color_percentage` 已由 BaseWWTask 包内实现覆盖，不能据旧框架差集重复添加。`ensure_capture` 在 AutoCombat.enable 的 UI启动路径存在，本轮实际Host轮询绕过该路径；后续支持通用 enable/用户切换时须迁移真实启动合同。

NativeHost现只实例化自动战斗并设置 context config；通用一次任务还需实际 after_init、before_run/after_run 和 registry生命周期。BaseWWTask.before_run 调用账号feature verification，after_run延迟导入任务分类与Daily清绑定，不能省略来通过旧依赖阻断。

`account_feature_verification.begin_task_run` 在分类前就导入 MultiAccountDailyTask；即使某任务最后被 classify 排除，这个入口仍拉入真实Daily/Qt闭包。其 `region` 延迟 import config.blur_area，`read_code` 直接读取 executor.config['ocr'] 与 executor.ocr_lib('default')，不经过普通 task.ocr 的text_fix和错误截图。当前native executor缺这两个接点。迁移必须保留同一个原始OCR引擎入口及私密crop不落盘合同，不能用普通OCR结果或空身份代替。

## Daily/MultiAccount必须共用同一个账号数据根与原服务

只绑定 `NativeConfig.config_folder` 不能完成账号迁移，以下是不同来源的真实路径合同。

| 来源 | 当前路径/全局合同 | 原生装配所需的最小改变 |
|---|---|---|
| account_runtime_bootstrap.py | `_default_root()` 为源码 `__file__.parents[2]`；无version则import config；默认安装旧 StartController启动guard | 在生产task构造前用明确 data_dir、manifest version、`install_start_guard=False` 调现有 initialize；原生任务入口仍执行同一 integrity guard |
| DailyTask.py:89/93、MultiAccountDailyTask.py:84/85 | 导入时 `get_relative_path` 以 cwd 固定 configs/daily_profiles、MultiAccount、multi_account_progress | 所有 root绑定必须发生在相关模块导入前；改为实际账号服务 paths 或显式包内path服务，不能让 data与payload混用 |
| ConfigPaths.from_root | root/configs中的 account_master_config、daily_profiles、account_runtime_state、MultiAccountTask；安装根的 integrity incidents | 复用已有 ConfigPaths与只读master/修复working合同 |
| AccountRepository.__init__ | root的账号/序列/账号备份；configs旁的运行状态/账号、运行状态/全局.json | 与既有repository同根，不另造GameFrame账号账本 |
| AccountPublishService | configs/published、bundles、active、维护事务与configs/accounts镜像 | 保留原事务恢复与完整性检查顺序，不直接写影子JSON替代服务 |
| get_evidence_service、diagnostic_storage | 默认LOCALAPPDATA/OKWW/CompletionEvidence；storage_path默认诊断策略REPO读取 runtime_storage/storage_migration | 原生显式 data_dir/EvidenceRepository与executor service注入；DailyTiming也必须使用该同一服务，不能继续读默认全局 |
| storage.get_config_backup_dir | 读取旧 og.executor.global_config，再解析安装目录storage配置 | 使用现有纯 resolve_config_backup_dir 和明确设置/root，保留数据迁移gate；配置/导出路径不从包源码推导 |

`initialize_account_runtime` 已组合 ConfigBackup、AccountConfigBundle事务恢复、AccountPublish恢复、Integrity、Repository、SequenceSnapshot；无需新 bootstrap状态账本。新native ZIP不带私人账号资料；需要明确加载/迁移既有受保护配置包后才可运行账号任务。源码包中存在旧配置恢复模块不等于授权读取旧安装。

`install_start_guard=False` 只避免向旧GUI StartController装wrapper，不是免除启动校验。ConfigIntegrityService.guard_task_start 的合同是设备/窗口操作前检查；当前 GameFrame worker顺序是 manifest.load → create_device → package.run，把guard放在Host构造或Daily.run已晚于设备创建。最小装配方案是在设备创建前提供包负责的device-free prepare/preflight接点，native包在此初始化明确root/version并调用现有 `TaskStartGuard.check` / `AccountRuntime.require_ready`，核心只调用该包接点，不导入账号源码。旧GUI继续使用真实 StartController wrapper，CLI/调度与后续 run入口都复用同一service，失败明确阻止设备创建。实现仍待下一批授权，不能把此设计写成当前已完成。

`AccountSelectionService` 和 `AccountVerificationService` 已只依赖包内身份规则。`LoginFlowService.switch_to_account` 调用生产task的 dropdown选择、稳定页面、retry、登录前verify、点击、ensure_main、失败/停止证据及MouseReset保存/恢复；只需迁移它的异常类型和平台接点。TestAccountSwitchTask继续复用此链与生产MultiAccount方法，不能新增另一份选账号/注销/登录实现。

## GUI/og可提取的最小部分与身份边界

DailyTask顶层 `QThread`/`QApplication` 用于 `_refresh_gui` 的线程检查；文件选择、确认对话框、DailyProfileDialog、combo/card更新是已有GUI职责。MultiAccount的序列对话框/refresh同样属于GUI，但 `config_type`的 options/sub_configs计算、当前账号/序列选择更新是业务数据，原生仍需执行。`validate_config(CURRENT_SEQUENCE)` 用 QTimer在Config写入后刷新，不能去掉timer后在写入前刷新旧值；需同一已提交配置合同下的显式通知接点。

最小分离是保留现有数据计算、repository和protected import/preflight/confirmed事务，把控件操作和选择文件/用户确认交给明确UI服务。原生没有UI的运行入口只调用业务路径；用户请求编辑/导入时必须使用已有服务的明示路径与确认合同，不能以None/False默认掩盖不支持。

Host泛化不能将类改名为 HeadlessDailyTask/HeadlessMultiAccountDailyTask：

- daily_timing.py:149/179 按真实 `type(task).__name__` 决定是否记录每日耗时。
- account_feature_verification.py:139/170/260 按类名决定账号身份要求和当前多账号owner。
- evidence/service.py:138/144、DailyTask.py:2192 按类名区分MultiAccount/WorldBoss/周乐园行为。

这会产生无异常的义务跳过；应保留真实生产类实例/名称与provider服务。当前HeadlessAutoCombat实测通过不证明同样改名方式适用于每日任务。

原生装配顺序应是：明确data root并完成同一启动guard → native provider绑定 → 创建真实生产类及同一registry → 使用原 after_init配置加载/业务选项计算 → 原 before_run身份核验 → 原 run → finally原 after_run清绑定和task输入释放。数据计算与UI刷新可分离，不能跳过before_run或改class name来断开依赖。代表性的最小检查是坏master使设备工厂调用数为0、同一临时root的各repository/service路径一致、原Daily/MultiAccount类名下身份与耗时入口实际执行；账号测试继续复用原切换链。

DailyTask.run用 account_input_guard 与 executor._daily_reserve_policy；farming_task_scheduler直接调用同一registry里的生产farm/weekly方法；MultiAccountDailyTask.run将Daily置于同一身份guard和sequence snapshot下，并沿用TaskRunCoordinator。自动战斗后台服务只保留启用意图；前台Daily/challenge进入战斗时通过共享combat loop发送输入。原生全任务调度必须继续保持这一个输入owner。

## 按真实依赖推进的最小批次

1. 通用平台/生命周期：NativeTask的实际scroll/back/text/swipe/pause、task registry、before/after与当前owner；WWOneTime、MouseReset平台合同。核验普通服务与前台任务不能并发输入。
2. 导入与少依赖任务：Solo、拾取、登录、对话、传送；MaterialPlanner的实际滚动与子任务registry；SecondSol/Piano/Event只迁它们真实需要的平台/图标数据，不拉入整个GUI。
3. 实例与资源任务：Domain/Forgery/Simulation/Tacet/Nightmare/Weekly/FarmEcho/WorldBoss/Garden。需要奖励/配额的任务同时接已有明确账号root与journal，保留完成后验，不能只测空页面。
4. 挑战与活动：AutoAbyss、AutoSeaRuins、EchoesRemain、CharacterTrial、Tiangong、ResonanceSimulation。覆盖各自真实额外FeatureSet、队伍/能量/信物、人工pause及热键合同。
5. Daily与账号族：先完成明确root与UI服务分离，再装配Daily、MultiAccountDaily、MultiAccountWeeklyGarden、TestAccountSwitch；复用原选择/别名/掩码身份/verify/retry/logout/login和sequence/完整性/证据服务。不能把兼容运行或新造切号流程当完整native迁移。

截至调查时，第1/3/5批中的方法/root装配尚未完成，表中26项不可直接原生执行；两个导入成功的任务也缺运行验收。每批按其真实变化做最小检查，最终用实际被禁止旧依赖的安装包入口覆盖生产run链；离线图像与设备动作只证明该场景，不证明真实账号/实战成功。
