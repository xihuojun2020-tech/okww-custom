# GameFrame 第二轮任务、场景与游戏辅助模块审查

日期：2026-10-11。基线为已合入的 `v1.97.63` / `3b076c75`，另核对了 `v1.97.61..v1.97.63` 在任务区的七个变更文件。范围是 `src/task` 的全部 76 个 Python 文件、`src/scene/WWScene.py`，以及顶层 `src` 中直接承载游戏规则或设备辅助的 11 个模块。对全部 88 个文件做了逐文件语法及职责/依赖扫描；沿多账号切换、每日完成、消费账本、战斗恢复和后台导航的具体调用链人工点读。本轮只读，没有修改产品或测试代码，没有启动游戏、模拟器、OK/TaskTestCase 实例，没有读取真实账号/设备或访问 NAS。88 个文件由仓库 `.venv\Scripts\python.exe` 的 `ast.parse` 解析通过；这只证明源码可解析，不代表分支行为或设备功能验收。

## 结论与可定位证据

本轮没有发现可由现有源码、契约和离线证据单独证明、值得立即修改的新产品缺陷。以下关键链条有实际实现，迁移时应保留其语义：

| 链条 | 核对位置与结果 |
|---|---|
| 多账号身份与周期 | `MultiAccountDailyTask.create_run_snapshot` 647 行冻结 profile ID；`_guard_account_transition` 1294 行比对冻结身份；`_progress_key`/`_check_progress_date` 772/793 行使用游戏日并阻止跨日续跑；`_mark_done` 1229 行写稳定 ID，`_reconcile_failures` 830 行避免未解决失败被完成标记掩盖。`game_period.py` 的每日/每周 04:00 北京边界由共享函数提供。|
| 测试任务与生产切换 | `TestAccountSwitchTask.run` 160 行取得同一个 `MultiAccountDailyTask`；连续 A1/A3/A4 先由 `create_run_snapshot(..., short_names=True)` 精确解析，再调用 `_select_and_login_sequence`。该生产方法 3670 行逐账号使用 `_select_and_login_specific` → `switch_to_account`，其选择、登录前核验、退登和登录实现不另造一套。仅静态核对，未执行真实切号。|
| 账号完成与消费 | `MultiAccountDailyTask._run_daily_account` 2159 行只在子任务未抛错后 `_mark_done` 并持久化；`DailyTask._finish_daily_rewards` 737 行对未读出活跃度/未刷满抛错，`record_last_completed` 1268 行写失败会传播。`farming_task_queue.require_resolved_claims` 阻止已删除任务遗留的 pending；凝素、世界首领、周本分别在真实领取前建 pending，核验后 resolve。|
| 战斗结果与输入 | `BaseCombatTask.combat_once` 597 行把死亡与未确认脱战抛回调用者；`DomainTask._finish_domain_combat` 222 行要求正向领奖画面，`AutoAbyssTask._run_combat_and_wait_result` 1356 行等待结算，`AutoSeaRuinsTask._fight` 475 行等待阶段结束。`BaseCombatTask._release_combat_inputs` 130 行记录原始输入后端并逐键释放；`AutoCombatTask.set_enabled_from_ui` 72 行是明确关闭偏好的路径，普通错误经 `handle_execution_error` 保留 enabled。`SoloCombatTask` 仅允许单人，后台多/单模式用 `_background_combat_mode` 区分。|
| 场景与后台导航 | `WWScene.reset` 清除帧相关缓存。`trigger_navigation.advance` 每 tick 至多一次输入并受 `_navigation_epoch`、窗口、身份、分辨率约束；`ui_transition.Transition` 有超时、次数与目标身份状态。迁移后的帧更新必须继续使场景缓存失效，调度器必须继续保证单一输入所有者。|

`BaseCombatTask.combat_is_active` 183 行和 `perform_combat_rotation` 207 行对普通探测/动作异常持续退避恢复，外层 `DomainTask._finish_domain_combat` 的 600 秒上限在内层恢复期间不会触发。单看循环容易把它误判为需要新增前台截止时间；但 `tests/TestBaseCombatTask.py` 明确要求多次错误后继续恢复并核对 stop/death/handoff 分流，`docs/research/2026-10-11-gameframe-native-combat-boundary.md` 也要求保留该行为。没有持续错误的实机证据或相反契约，本轮**不列为确认 bug，也不建议擅自加总重试关闭或把错误变成假完成**。实际窗口消失、恢复 hook 故障后的运行表现仍需后续设备验证。

`v1.97.63` 新增的周本路径也逐段核对：`DailyTask.check_weekly_boss` 1934 行先按账号和计划 revision 判断是否要检查；`confirmed_weekly_claims` 汇总同账号旧账本和刷取实例账本，并在任何周本 pending 时阻止下一次周本领取；周日由 `verify_weekly_remaining` 读取本周剩余次数，未核实则通过 `WeeklyBossSundayVerificationError` 阻止多账号切到下一个账号；`run_weekly_queue` 在有限材料目标后调用既有 `WeeklyBossTask.run_for_plan` 继续核实游戏每周额度。新刷取队列的 `require_resolved_claims` 会暂停该队列的所有消费；旧版无队列账号在普通日周本待补检后可以继续其他每日事项。两种策略确有差异，但当前资料没有表明旧路径会因此重复领取周本或记错账号，所以不把“其他品类继续执行”单独判为缺陷。

## 迁移需兑现的边界

- `BaseWWTask`、`BaseCombatTask`、`WWOneTimeTask` 与多数具体任务仍继承或调用 `ok` 的任务、OCR、帧、输入和计时 API；把文件移入 gamepack 后必须由真实核心/适配器履行这些方法及停止、暂停、异常语义。AST/import 成功不证明任务可运行。
- `src/globals.py` 从可执行文件相对路径加载 `assets/echo_model/echo.onnx`，`sea_ruins_vision.py`、`story_skip.py` 等按源码位置找图像；gamepack 安装布局必须带上素材并重新核对路径。两个 YOLO 后端的推理错误传播已由第一轮修复，本轮没有重复修改。
- `src/win32_login_input.py` 是真实 Win32 SendInput/前台窗口交付层；多账号退登还使用 `logout_capture.py`。替换设备后端时保留窗口所属进程、点击投递和登录前 OCR 核验，不能把“点击已调用”当成“选中目标账号”。
- 特征码核验 `account_feature_verification.py` 区分读取失败、未绑定、冲突、身份不符；`FeatureRun.guard` 固定当前窗口、执行任务和账号绑定。`CharacterTrialTask` 在游戏完成后仍需结束身份复核与保存证据，失败只留待核验而不写已完成。

## 文件级覆盖清单

以下每个文件均在本轮范围内完成文件级结构/风险扫描；深读只针对上面的调用链。列出范围是为了让后续迁移逐模块追踪，不能解释为 76 个任务逐条 OCR 路径已验收。

| 业务区域 | 已覆盖文件 |
|---|---|
| 任务基础、战斗、导航、切号（16） | `account_feature_verification.py`, `AutoCombatTask.py`, `AutoLoginTask.py`, `AutoPickTask.py`, `BaseCombatTask.py`, `BaseWWTask.py`, `DailyTask.py`, `DomainTask.py`, `FastTravelTask.py`, `MouseResetTask.py`, `MultiAccountDailyTask.py`, `MultiAccountWeeklyGardenTask.py`, `SoloCombatTask.py`, `TestAccountSwitchTask.py`, `trigger_navigation.py`, `ui_transition.py` |
| 每日资源、计划和账本（25） | `daily_observation.py`, `daily_reserve_policy.py`, `FarmEchoTask.py`, `farming_task_queue.py`, `farming_task_scheduler.py`, `forgery_quota_plan.py`, `forgery_quota_progress.py`, `forgery_targets.py`, `ForgeryTask.py`, `MaterialPlannerTask.py`, `NightmareNestTask.py`, `SimulationTask.py`, `TacetTask.py`, `tacet_targets.py`, `weekly_boss.py`, `weekly_boss_plan.py`, `weekly_boss_progress.py`, `WeeklyBossTask.py`, `world_boss_material_plan.py`, `world_boss_material_progress.py`, `world_boss_materials.py`, `WorldBossMaterialTask.py`, `echoes_support.py`, `echoes_remain.py`, `echoes_continuation.py` |
| 活动、挑战、其他任务与视觉规则（35） | `abyss_allocation.py`, `abyss_cycle_progress.py`, `abyss_energy.py`, `abyss_team_planner.py`, `AutoAbyssTask.py`, `AutoSeaRuinsTask.py`, `ChangeEchoTask.py`, `character_trial.py`, `CharacterTrialTask.py`, `DiagnosisTask.py`, `EchoesRemainTask.py`, `EnhanceEchoTask.py`, `EventTask.py`, `FarmMapTask.py`, `FiveToOneTask.py`, `GardenTask.py`, `KRLauncherSwitchTask.py`, `MergeEchoTask.py`, `piano.py`, `PianoTeachingTask.py`, `process_feature.py`, `resonance_simulation.py`, `ResonanceSimulationTask.py`, `sea_ruins.py`, `sea_ruins_recovery.py`, `sea_ruins_tokens.py`, `sea_ruins_vision.py`, `SecondSolTask.py`, `SkipBaseTask.py`, `SkipDialogTask.py`, `story_skip.py`, `tiangong_treasure.py`, `TiangongTreasureTask.py`, `weekly_garden.py`, `WWOneTimeTask.py` |

任务清单合计 76 个；场景另含 `src/scene/WWScene.py`。顶层游戏辅助 11 个：`src/__init__.py`, `activity_catalog.py`, `game_period.py`, `globals.py`, `Labels.py`, `logout_capture.py`, `nightmare_nests.py`, `OnnxYolo8Detect.py`, `OpenVinoYolo8Detect.py`, `recording_policy.py`, `win32_login_input.py`。本轮没有读取账号配置、NAS 诊断包或真实游戏画面；图片识别阈值、窗口投递、角色轮转效果和最终 gamepack 启动仍属后续验证，不因静态覆盖而视为完成。
