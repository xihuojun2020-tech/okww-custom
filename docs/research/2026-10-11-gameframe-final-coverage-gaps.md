# GameFrame 最终功能覆盖对照与剩余缺口

本文保留 v71 历史审计状态。后续修复及 v1.97.76 最终状态见 [最终覆盖核查](2026-10-11-gameframe-final-coverage.md)；不要将下列旧缺口当作当前版本结论。

审计日期：2026-10-11。结论：**原生迁移尚未完成**。29个内置任务已完整注册，核心账号计划、序列、完成证据、角色代码和用户任务已有原生入口，但部分用户可见行为仍未接通。注册数量、生产代码复用和离线测试不能证明真实游戏链路全部成功。

本轮只读检查 `config.py`、`src/gui` 业务入口、原生 manifest/plugin、GameFrame GUI/controller/device、native metadata/configuration/host、定时与存储服务。唯一写入是本文档。未重复全量测试，未启动设备、枚举窗口、执行ADB/SDK、连接NAS或执行账号动作。共享工作区仍有v71集成中的修改；下文“存在”表示审计时源码存在，不保证该修改已发布。

设备选择、热键、通知、一般截图/OCR工具和存储已有详细计划：`docs/superpowers/plans/2026-10-11-gameframe-final-surfaces.md`。本文补充业务覆盖与额外缺口。

## 1. 29个内置任务：注册完整，展示与实测另算

用AST静态读取 `config.py` 的实际 `onetime_tasks` / `trigger_tasks`（忽略注释），与 `gamepacks/wuthering_waves_native/manifest.json` 的 module/class 对照：旧版29、原生29、缺失集合为空。未导入或构造任务。

| 类型 | 任务 | 当前原生入口 |
| --- | --- | --- |
| 每日与多账号 | DailyTask、MultiAccountDailyTask、MultiAccountWeeklyGardenTask | manifest可见，生产类复用 |
| 声骸/材料/周常 | FarmEchoTask、WorldBossMaterialTask、GardenTask、WeeklyBossTask | manifest可见，生产类复用 |
| 挑战 | AutoAbyssTask、AutoSeaRuinsTask | manifest可见，生产类复用 |
| 活动 | EventTask、PianoTeachingTask、SecondSolTask、EchoesRemainTask、ResonanceSimulationTask、CharacterTrialTask、TiangongTreasureTask | manifest可见，生产类复用 |
| 内部/隐藏任务 | NightmareNestTask、TacetTask、ForgeryTask、MaterialPlannerTask、SimulationTask、TestAccountSwitchTask | manifest注册但visible=false，主启动列表及配置页过滤 |
| 后台服务 | AutoCombatTask（ID为auto-combat）、SoloCombatTask、AutoPickTask、AutoLoginTask、AutoDialogTask（SkipDialogTask模块）、FastTravelTask、MouseResetTask | 七项service注册；会话内启用/停用 |

六个隐藏类自身也设置 `visible=False`，因此不能单凭隐藏认定迁移遗漏：材料/副本能力由每日账号计划调用；切换测试原来也是隐藏入口。若用户希望直接运行隐藏测试，应明确新增诊断入口，而非把所有内部任务一律展示。

旧版 `navigation_sections.py` 还隐藏 PianoTeachingTask、SecondSolTask、EchoesRemainTask，原生manifest却展示这三项。**这是可见性不一致**，需要选择保留旧产品目录还是明确恢复这些任务；不能宣称导航行为已一致。`ActivityHubTab` / `TestHubTab` 属于旧路由，当前主导航以 `navigation_sections` 为准，不能按文件存在重复计算产品入口。

注册与生产规则复用不证明每个任务捕获、键鼠、OCR、战斗、登录和结算已在实际游戏验收。29项均需在最终交付中标明实测范围；本轮没有新增硬件成功证据。

## 2. 已有的实际迁移

| 功能 | 原生证据 | 状态与限制 |
| --- | --- | --- |
| 任务运行、暂停/恢复、停止、后台服务启停 | `gameframe/gui.py`、controller、native host会话 | 已接通；Stop和Pause应保留服务偏好，Disable才改偏好 |
| 任务参数和技能键/月卡/角色全局参数 | `native_metadata.py`、`NativeConfigurationTab` | 三类全局配置存在；数字、选项、多选、顺序列表、JSON、标签、按钮及文件字段有渲染器 |
| 首账号、账号包导入/导出、身份修订、完整性检查 | `ManagementWindow`、账号编辑/事务服务 | 已有管理入口；游戏特征码读取另见缺口 |
| 每日账号方案、任务排序/刷取队列、凝素额度、首领材料和周本计划 | `AccountConfigTab`复用对应专用widget | 已迁移；不是用任务JSON替代全部业务表单 |
| 序列成员、固定槽位、参与开关和执行顺序 | `SequenceManagementTab`、`AccountSlotEditor`、`account_slots.py` | A1–A10 / B1–B10及历史序列支持；固定序列按槽位排序 |
| 账号提醒和备注 | `AccountReminderPanel`由账号编辑器使用 | 已有表单和保存路径；外部通知投递不等同已迁移 |
| 执行总览、账号状态与每日耗时 | `native_overview.py`、`NativeExecutionOverviewDialog`、`DailyTimingDialog` | 原生只读运行状态/历史入口存在 |
| 完成证据查看、原图复制/导出、回收/恢复/删除 | `CompletionCheckTab(None)`由ManagementWindow使用 | 已迁移已有证据操作；手工拍摄需要live owner |
| 每日配置备份、验证、事务恢复、旧序列恢复、清理预览 | `native_maintenance.py`、`NativeMaintenanceTab` | 已迁移，独占锁和提交后重载行为存在 |
| 日志和诊断 | local-only DiagnosticStatusCard | 本地管理界面存在，不代表NAS发布/上传链路已在原生运行验收 |
| 游戏包安装、验证、更新、owner停机与重启 | GameFrame包更新及NativeGamePackUpdateCard | 已有；源码目录无files.json时正确不给替换入口 |
| 角色代码 | NativeCharacterCodeTab、native_characters、严格loader及live reload | v71源码已接通固定类身份、校验、保存/重置/模式及owner应用；本轮未重复审角色细节 |
| 用户任务及脚本包 | NativeUserTaskTab、native_user_tasks、native_user_task_bundles、host reload | v71源码已有编辑、验证、注册、包导入及重载；不等同任意旧ok-script脚本自动兼容 |

## 3. 除上一轮计划以外的真实缺口

### P1：账号游戏特征码读取与确认绑定没有原生可用入口

`ManagementWindow.refresh` 明确禁用 `read_feature_button`，提示“请在任务窗口读取特征码”。实际 `gameframe/gui.py` 没有对应账号选择/读取/确认绑定控件。旧 `AccountConfigTab.read_feature_code` 依赖 `og.executor` 和 `request_capture(..., feature_code=True)`，不能直接在无设备管理owner运行。

这不是一般OCR按钮：它涉及选定账号revision、连续一致读数、用户确认真实账号、身份重绑定事务及备份。最小实现应由live owner读取，管理窗口按原服务预览和确认绑定，拒绝账号或revision在等待时变更。后台不能默默绑定。任务自动首尾身份核验不替代用户显式建立绑定入口。

### P1：需要设备的任务配置动作只能显示禁用按钮

`TaskMetadata._config_type` 给动作分配ID，并区分management/owner/requires_device。`NativeConfigurationTab._widget` 将requires_device按钮禁用。当前GameFrame主窗口提供运行/服务/重载，但没有通用动作面板或将这类管理请求送给live session的桥接。

不要新增第二任务对象执行回调。下一步应静态列出当前29类及已安装用户任务的实际callback，确认哪些被禁用；仅把确实需要的动作接到现有 `invoke-action` 协议。现有 `clear_current_character_scan` 被明确标为no-device，可在配置owner执行，不属于缺失。管理账号/序列按钮已路由ManagementWindow，也不应重复列缺。

### P1：程序启动即恢复辅助服务的产品行为没有接通

旧 `AssistantHubTab` 明示应用打开自动启动，开关决定服务，暂停不改保存开关。原生host会在会话启动后读取服务偏好；但 `GameFrameWindow.__init__` 只加载包、选任务和启动GUI定时器，没有自动启动选定包会话。**保存偏好恢复与启动应用后自动建立会话是两件事**。

全量迁移需要定义并实现明确的包/设备选择后自动会话启动行为，保留用户已禁用配置，不能为升级强开战斗。首次没有设备配置时应留在可配置界面。最终产品需让用户理解会话尚未启动与服务已保存启用的区别。

### P2：主任务页的当前账号/序列快捷选择与导航语义没有完整迁移

旧 `TaskHubTab` 使用MultiAccountDailyTask配置作为统一来源，提供当前序列/账号选择、运行时已核验账号展示和“无序列”解释。原生管理页可编辑相应task配置，账号/序列管理也存在；因此底层能力并未消失。但主启动页没有旧账号上下文面板，不能称同样的入口体验已经恢复。

旧任务分类、活动时间排序、不常用任务、辅助类别和工具类别也未被主窗口平面列表复用。最小修改是复用metadata及现有分类函数/纯数据规则，显示账号上下文并在运行时锁定选择。不要另建第二“当前账号”配置。正确性优先于完整复制旧排版。

### P2：语言选择及原生界面翻译缺失

旧SettingTab有简中/繁中/英语/西语/日语/韩语/系统语言选择。GameFrame GUI混合英文固定文本，原生管理页多为中文固定文本；没有相应选择或翻译安装路径。native host的 `translate=gettext.gettext` 是接口默认值，不能证明启动时按保存语言安装catalog；插件和管理入口也未发现对应安装调用。

迁移应复用已有gettext catalogs，明确保存语言及重启/即时应用策略。OCR locale与界面语言应按实际原有契约处理；不要简单把文本换成中文就宣称多语言完成。旧主题已经固定浅色，暗色切换不是遗留必须恢复项。

### P2：Basic Options / App Launcher 偏好不完整

native GLOBAL_METADATA目前只含 Game Hotkey、Character Config、Monthly Card Config。旧Basic Options的托盘关闭、后台静音、窗口自动调整、游戏退出时退出应用、DirectML选项、启动游戏、启动器关闭、DX11等没有等价原生设置面板；App Launcher也没有对应完整入口。

应逐项确定行为：关闭托盘与当前closeEvent实际退出不同；当前已存在绝对launch_command启动机制，但没有旧启动器配置的友好入口；后台SendInput要求前台，不能靠保留旧选项假装旧PostMessage语义已覆盖。DirectML/推理配置需先对照真实模型执行后端，不能添加不起作用的开关。HDR/夜间模式与分辨率检查是config连接行为，不是仅有设备下拉框就完成。

这批设置中设备/启动配置可与上一轮Task1合并；其余真实行为按独立小项实现。不要复制所有旧字段却不执行它们。

## 4. 定时、退出及多Windows用户：精确边界

**定时已经存在。** NativeScheduleTab提供一次、每天、每周一、每月1日、间隔天/小时、开始时间、最长运行时间、启停、预览、创建/更新、删除和刷新。NativeSchedule绑定包、数据目录及当前Windows用户，使用InteractiveToken；任务过滤由真实 `support_schedule_task` 元数据决定。设备目前仍需JSON，属于上一轮设备图形化缺口。周一/月1日是当前明确固定语义，不应描述成任意星期/日期编辑器。没有本轮Windows计划任务COM创建/执行的实测证据；旧系统计划是否需要导入也未证明，不能承诺已自动迁移。

**成功后退出行为已接通。** NativeBaseTask加入Exit After Task；native host成功运行后调用设备stop_target并返回exit_requested；session据此退出，GUI在worker返回0且收到请求时关闭。Windows.stop_target验证选定HWND、PID/create-time，释放输入后终止选定游戏进程。不是全局kill，也不是Windows关机。普通窗口关闭则走controller owner清理。旧DailyTask每日完成后退登和多账号结束保留最后账号仍由复用生产规则承担；不能与“关闭游戏/应用”混为一谈。关机不在当前注册需求证据中，不新增。

**手动多Windows用户组只有基础隔离能力，缺少显式产品组映射。** A/B固定序列是游戏账号槽位组，没有windows_user字段或OS用户绑定。NativeSchedule确实按当前Windows用户隔离计划，launcher可通过不同显式data_dir运行；这支持用户手动登录不同Windows用户并各自使用独立资料，但当前GUI没有“Windows用户—资料根—账号组”映射/说明入口，也没有跨用户状态汇总证据。若用户要求组支持，应明确每个用户使用哪个data_dir/序列并显示当前用户上下文；不要宣称A/B就是Windows用户组。OS切换保持手动，禁止恢复KR自动切换或多实例系统。

## 5. 废弃项、范围和验收顺序

KRLauncherSwitchTask、DiagnosisTask、EnhanceEchoTask、ChangeEchoTask在config中已注释；不是29项缺失。历史KR SequenceBackups可用于迁移读取，不代表恢复产品功能。旧暗色主题、未注册业务、旧框架安装器兼容不应自动成为迁移目标。用户脚本必须按当前受支持的Native API/脚本包转换契约验收，不能以“编辑器存在”保证所有第三方代码成功。

建议先完成设备图形化和账号特征码绑定，再接真实设备动作、辅助自动会话启动及明确的当前账号上下文；随后补语言和有证据的Basic/App Launcher偏好。存储authority绑定与用户组data_dir约定需在搬运资料前明确。已迁移的账号计划、证据、角色、用户脚本、定时和退出路径保持现有owner协议，避免重复实现。

验收分开记录：静态注册/GUI入口、fixture/Replay行为、真实Windows游戏运行、真实定时触发、真实账号切换、NAS上传发布。现阶段只能确认前两类中已有记录覆盖的部分；本轮只是静态对照。未列为缺口不等于已完成硬件验收，最终不能使用“29项注册齐全”作为“全量功能迁移完成”的结论。
