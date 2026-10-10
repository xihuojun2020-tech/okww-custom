# 鸣潮其余任务原生迁移边界（2026-10-11）

最初调查覆盖生产 config 中全部 22 个一次任务和 AutoCombat 之外的 6 个后台服务：28 个独立进程中，只有 `MaterialPlannerTask` 和 `SoloCombatTask` 完成禁止旧依赖的真实导入；其余 26 个在实际旧依赖处中止。后续已实施账号预检、原 Daily/MultiAccount 类装配及配置刷新，并完成七项原生账号检查和 193 项旧账号回归；本文末尾记录该批结果。导入或离线检查通过不证明真实游戏任务完成。

最初调查只读，发生于本轮通用平台迁移开始前；下表保留这一时点的证据。后续实施创建了真实生产任务实例，使用合成账号配置、临时目录和 ReplayDevice；没有启动 OK 应用、游戏、模拟器、真实捕获/输入、登录账号、读取私人配置或操作 NAS。

## 真实导入与静态闭包怎样区分

从 `scripts.build_gamepack.source_metadata` 读取真实注册表。每个任务独立启动项目 `.venv` Python 的 `-I -B` 进程，cwd/Config root 都在临时目录；先 `combat_api.configure(native=True, data_dir=...)`，再用 import finder 禁止 `ok`、PySide6/PyQt、qfluentwidgets、custom_ok、config、main，最后只 import 生产模块。未伪造旧模块或任务方法。

另用 AST 枚举 src 中每个模块的 Import/ImportFrom 及函数内延迟依赖，追到所有包内可解析模块。全函数候选闭包包含 BaseWWTask.after_run → DailyTask → MultiAccountDailyTask/GUI，因此大多数任务的保守闭包为 176–185 个 src 模块；这不是运行时会同时导入的模块数量。补充核对发现 Daily、MultiAccountDaily、Nightmare 等文件底部的 config/run_task 导入原本在 `if __name__ == '__main__'` 外，确实会阻断常规原生导入；此前将它们当作 guard 内脚本依赖的描述有误。本轮已将这类导入移入真正的 guard。下表仍记录最初独立进程遇到的第一个阻点。

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

`install_start_guard=False` 只避免向旧GUI StartController装wrapper，不是免除启动校验。ConfigIntegrityService.guard_task_start 的合同是设备/窗口操作前检查；最初 GameFrame worker顺序是 manifest.load → create_device → package.run，把guard放在Host构造或Daily.run已晚于设备创建。本轮核心负责人已在 create_device 前实现可选 package.prepare；原生包调用 `prepare_native_account_runtime(data_dir, version)`，账号侧复用现有事务恢复、Integrity/Repository/SequenceSnapshot和 `AccountRuntime.require_ready`。核心只调用包接点，不导入账号源码；负责人报告坏 prepare 时设备工厂调用数为 0。旧GUI继续使用真实 StartController wrapper。

`AccountSelectionService` 和 `AccountVerificationService` 已只依赖包内身份规则。`LoginFlowService.switch_to_account` 调用生产task的 dropdown选择、稳定页面、retry、登录前verify、点击、ensure_main、失败/停止证据及MouseReset保存/恢复；只需迁移它的异常类型和平台接点。TestAccountSwitchTask继续复用此链与生产MultiAccount方法，不能新增另一份选账号/注销/登录实现。

## GUI/og可提取的最小部分与身份边界

DailyTask顶层 `QThread`/`QApplication` 用于 `_refresh_gui` 的线程检查；文件选择、确认对话框、DailyProfileDialog、combo/card更新是已有GUI职责。MultiAccount的序列对话框/refresh同样属于GUI，但 `config_type`的 options/sub_configs计算、当前账号/序列选择更新是业务数据，原生仍需执行。`validate_config(CURRENT_SEQUENCE)` 用 QTimer在Config写入后刷新，不能去掉timer后在写入前刷新旧值；需同一已提交配置合同下的显式通知接点。

最小分离是保留现有数据计算、repository和protected import/preflight/confirmed事务，把控件操作和选择文件/用户确认交给明确UI服务。原生没有UI的运行入口只调用业务路径；用户请求编辑/导入时必须使用已有服务的明示路径与确认合同，不能以None/False默认掩盖不支持。

Host泛化不能将类改名为 HeadlessDailyTask/HeadlessMultiAccountDailyTask：

- daily_timing.py:149/179 按真实 `type(task).__name__` 决定是否记录每日耗时。
- account_feature_verification.py:139/170/260 按类名决定账号身份要求和当前多账号owner。
- evidence/service.py:138/144、DailyTask.py:2192 按类名区分MultiAccount/WorldBoss/周乐园行为。

这会产生无异常的义务跳过；应保留真实生产类实例/名称与provider服务。最初 HeadlessAutoCombat 的测试不证明改名方式适用于每日任务；本轮 Host 已使用原生产类实例和名称，身份入口的真实执行检查见后文。

原生装配顺序应是：明确data root并完成同一启动guard → native provider绑定 → 创建真实生产类及同一registry → 使用原 after_init配置加载/业务选项计算 → 原 before_run身份核验 → 原 run → finally原 after_run清绑定和task输入释放。数据计算与UI刷新可分离，不能跳过before_run或改class name来断开依赖。代表性的最小检查是坏master使设备工厂调用数为0、同一临时root的各repository/service路径一致、原Daily/MultiAccount类名下身份与耗时入口实际执行；账号测试继续复用原切换链。

DailyTask.run用 account_input_guard 与 executor._daily_reserve_policy；farming_task_scheduler直接调用同一registry里的生产farm/weekly方法；MultiAccountDailyTask.run将Daily置于同一身份guard和sequence snapshot下，并沿用TaskRunCoordinator。自动战斗后台服务只保留启用意图；前台Daily/challenge进入战斗时通过共享combat loop发送输入。原生全任务调度必须继续保持这一个输入owner。

## 按真实依赖推进的最小批次

1. 通用平台/生命周期：NativeTask的实际scroll/back/text/swipe/pause、task registry、before/after与当前owner；WWOneTime、MouseReset平台合同。核验普通服务与前台任务不能并发输入。
2. 导入与少依赖任务：Solo、拾取、登录、对话、传送；MaterialPlanner的实际滚动与子任务registry；SecondSol/Piano/Event只迁它们真实需要的平台/图标数据，不拉入整个GUI。
3. 实例与资源任务：Domain/Forgery/Simulation/Tacet/Nightmare/Weekly/FarmEcho/WorldBoss/Garden。需要奖励/配额的任务同时接已有明确账号root与journal，保留完成后验，不能只测空页面。
4. 挑战与活动：AutoAbyss、AutoSeaRuins、EchoesRemain、CharacterTrial、Tiangong、ResonanceSimulation。覆盖各自真实额外FeatureSet、队伍/能量/信物、人工pause及热键合同。
5. Daily与账号族：先完成明确root与UI服务分离，再装配Daily、MultiAccountDaily、MultiAccountWeeklyGarden、TestAccountSwitch；复用原选择/别名/掩码身份/verify/retry/logout/login和sequence/完整性/证据服务。不能把兼容运行或新造切号流程当完整native迁移。

截至调查时，第1/3/5批中的方法/root装配尚未完成，表中26项不可直接原生执行；两个导入成功的任务也缺运行验收。每批按其真实变化做最小检查，最终用实际被禁止旧依赖的安装包入口覆盖生产run链；离线图像与设备动作只证明该场景，不证明真实账号/实战成功。

## 账号闭包实施与实际验证

这一增量基于已发布 `v1.97.65`。账号实施保留 DailyTask、MultiAccountDailyTask 原类名、LoginFlowService 及原 selection/alias/masked-phone/verify/retry/logout/login 方法。`account_task_support` 在明确的 native provider 下绑定 worker data_dir；旧入口仍委托真实 ok/config。没有读取旧安装的私人账号资料，也没有生成空 master 来通过 guard。

原生预检使用显式备份目录，复用既有事务恢复、发布、完整性检查、Repository和SequenceSnapshot。只有 `runtime.require_ready()` 成功才绑定完成证据服务；缺失和损坏 master 均抛出原 ConfigIntegrityBlocked，损坏源文件保持原字节。CompletionEvidence、配置、备份、导出和切号失败证据均使用 worker 的明确 root；singleton 已属于另一个 root 时明确拒绝混用。

Daily/MultiAccount 的原配置选项计算照常执行，控件刷新在 native 分支通知 context。NativeConfig 的 on_change 在 save_file 成功后执行，替代原 QTimer 等待已提交值的用途；验证失败或保存失败不会发送成功通知。周乐园消费者通过同一 executor registry 调用原 `_refresh_garden_status`。原生初始化和序列同步错误继续抛出，避免旧 GUI 的 best-effort catch 掩盖业务初始化失败。

身份特征码继续使用 executor 注入的原 raw OCR engine及其真实 backend配置；读取三倍放大的私密 crop，不走 task.ocr 的 textfix 或截图。完成证据使用原几何遮罩，版本来自准备好的 runtime；原生切号失败图在 annotation 前遮罩，即使 annotation 失败也只返回已遮罩副本。没有改动身份解析 regex或放宽置信度。

| 检查 | 结果与证据 | 范围限制 |
|---|---|---|
| `TestNativeAccountRuntime` | 7 项通过，4.114 秒；每例 fresh `-I -B -X utf8` 子进程，禁止 ok/PySide6/qfluentwidgets/config/main/custom_ok，使用真实可信合成 master 与 prepare | 原生账号源码、服务/root、配置与身份合同；未验证真实登录/每日运行 |
| 显式路径与坏 master | 现有服务绑定同一 worker root；与 cwd 无关的配置 sentinel 字节不变；缺 master不创建accepted master，坏master保留原字节且不初始化证据服务 | 预检失败确实传播；设备工厂为零由核心负责人测试证明 |
| 已提交序列与状态刷新 | 原 Daily/MultiAccount 实例从 S1切至空序列后，选项与已落盘值一致，当前不合法账号清空；真实周Garden消费者刷新，无GUI导入或Replay输入 | 数据/状态更新；旧GUI编辑器与文件对话框未迁入native worker |
| 原 Daily.before_run / after_run | “无序列”被原身份要求拒绝，raw engine未调用且无输入；数字绑定经三张独立新帧的原 FeatureRun/resolve/bind 后建立profile，after_run清除绑定 | Spy引擎只提供文本，真实freshness、crop、identity matching、binding、cleanup照常执行；不是OCR准确率测试 |
| raw OCR 与失败证据隐私 | crop实际尺寸为原区域3倍，独立内存；.79置信度返回不可读，001234保留前导零；正常及annotation故障图均遮住原私密区，原frame不变，events无rawcode | 读取/持久化边界合同；不代表真实OCR可读率 |
| 旧账号生产兼容回归 | 7组193项通过，0failure/error/skip，2.147秒：AccountRuntimeBootstrap、DailyTaskStatus、LogoutCapture、AccountSwitchEvidence、AccountFeatureVerification、MultiAccountDailyTask、AccountSwitch | 导入前生产overlay与临时旧Config root；未初始化OK应用/设备。同步两处旧og patch目标，并补齐冷启动capture测试的真实销毁夹具 |
| 原钢琴完整生命周期 | runtime负责人报告通过：prepare+原Multi/Daily registry，“无序列”原before_run分支、真实菜单识别/F down、Cancelled及Runtime cleanup；Daily绑定在before/after均清除 | 该离线场景已覆盖原任务生命周期；不扩展为全部非战斗任务的运行验收 |

原账号导入、恢复、确认和编辑对话框仍属于旧GUI；worker执行路径不调用这些控件方法。明确导入受保护配置包并接受master仍是新安装前置条件。其余资源/挑战任务、核心设备和已安装包的最终验收由对应负责人完成，最终发布记录应引用各自结果。
