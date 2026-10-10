# okww／ok 架构、功能复刻与跨游戏后台框架调研

调研日期：2026-10-10（北京时间）。目标：以鸣潮、原神等动作大世界游戏为主，规则驱动的自动战斗和日常任务；同一台 Windows 电脑、不使用虚拟机、不抢占主桌面键鼠，并为公开发布、闭源和商业化保留空间。

**结论：可以独立重写出与当前 okww 基本相同的功能；但仅替换图片不能得到跨游戏框架，也不能自动解决后台输入。** 对这组需求，优先研究“框架启动器＋游戏包＋执行环境适配器”。Windows 原生 Child Session 是当前用户下桌面隔离的优先验证方向。用户最新明确 Windows 用户由人手动切换，自动跨 SID 编排不属于当前需求。鸣潮可以另保留较轻的“同会话 WGC＋PostMessage”路线。MaaFramework 是任务流程层的候选，okww、BetterGI、OneDragon 是功能与设计参考。

原神的无虚拟机后台方案已有 BetterGI 桌面分身的公开实现；鸣潮在该独立会话中的启动、渲染、输入和长时间稳定性尚未验证。同机方案共享 CPU、GPU、显存和磁盘，因此“不抢键鼠”有实现路线，“对前台任务完全没有性能影响”不能保证。

现成代码和素材的许可证会影响闭源发布。当前本地 okww 与安装的 ok-script 是 AGPL；BetterGI、OneDragon 是 GPL；最新 ok-script 则是 Apache 2.0 加 Commons Clause 与附加限制。**重写代码不会自动清除复制素材、模型或衍生代码的授权条件。**

后续约束已补入[多用户、多账号、模拟器与低延迟调研](<E:/AI work/ok-wuthering-waves-master/docs/research/2026-10-10-multiaccount-emulator-lowlatency-feasibility.md>)：Windows 11、约四个用户串行执行且由人手动切换，各用户的游戏登录列表只显示十条已保存记录；未来支持 MuMu／雷电；素材仅暂时复用，之后逐项替换。补充报告第 8.1 节说明框架启动器与游戏包的边界。早期自动跨身份研究保留为可选参考。

## 1. 调研范围与证据等级

本报告结合三个并行子代理的源码调查及主代理的 GitHub 对照。覆盖本地业务、安装框架、自定义框架补丁，外部游戏自动化框架，以及捕获、输入、会话隔离、视觉推理和规则执行组件。

- **源码确认**：阅读实现、注册配置、许可证或官方 API 契约，可说明程序怎样工作。
- **项目文档**：项目声明的使用方式与限制，可作为公开实现证据，不能代替在本机复测。
- **架构判断**：根据接口边界提出的推荐与迁移方案，仍需实验验证。
- 本次没有启动游戏、安装驱动、启用 RDP、修改系统、运行战斗测试或读取私人账号配置／NAS 诊断 ZIP。只读取源码和公开资料，新增本报告。
- GitHub 检索按相关技术类别展开，不声称穷尽所有仓库。搜索摘要只用于发现项目；核心结论以源码、许可证和微软文档为依据。部分 GitHub 匿名 API 查询遇到限流，随后使用固定提交 raw 源码与临时稀疏检出。

### 1.1 三个版本必须分开

| 对象 | 本次基线 | 意义 |
|---|---|---|
| 本地定制 okww | 1.97.61；HEAD 4c0a4ad853d98bdc4474d3b6f43dc9c5ae03fcca；remote 为 xihuojun2020-tech/okww-custom | 本报告完整功能清单主要对应这个版本 |
| 本地安装 ok-script | requirements 锁定 1.0.190 | 当前运行时行为与许可证以这个安装包为准 |
| GitHub ok-script | 428bcd563292ac6451c84c0222e6b790d468215f | 新上游已拆分核心、Qt、Web；许可证也发生变化 |
| GitHub 原版 okww | b210632a251371cc0bbb1d0e28ce16ff35657824 | 公开基础版本；也配置 PostMessage＋WGC／BitBlt |
| BetterGI | 8a4db294362c682ca709ebeef205f77fca4d575e | 原神战斗、导航和桌面分身对照 |
| MaaFramework | 8963191215ca49d6b037802acd07d20a4213160a | 通用视觉任务与 Windows 控制器对照 |
| OneDragon／绝区零 | 9633c6a68e42ee7500cdf3fc9677dde2b51f1fe2 | 状态事件、条件规则和动作抢占对照 |
| GIA | 9d3357bbe6c50b5aff410d5695da4bd52e0dc26e | 旧原神战斗／日常方案；仓库已归档 |
| tignioj/minimap | dea82f9387fb7b3196d5b83dbcd1b5814ed78387 | 小地图视觉定位；README 声明停止维护 |

其他组件使用本次读取的仓库分支文档，未全部固定提交；维护状态属于本次观察，不保证以后不变。

## 2. ok 是什么，okww 增加了什么

ok-script 是基于计算机视觉的 Python 自动化运行框架。它提供窗口与设备发现、截图、输入、模板识别、OCR、任务调度、配置、界面、调试与发布支持。okww 在这些能力上实现鸣潮的页面语义、角色机制、战斗轮转与任务流程。

~~~mermaid
flowchart TD
    A[main.py 与 config.py] --> B[ok 运行时]
    B --> C[窗口 截图 输入]
    B --> D[模板 OCR 帧缓存]
    B --> E[任务调度 配置 UI]
    C --> F[BaseWWTask 游戏页面与导航]
    D --> F
    E --> F
    F --> G[CombatCheck BaseCombatTask]
    G --> H[BaseChar 与角色规则]
    F --> I[每日 副本 周本 活动]
    I --> G
~~~

### 2.1 启动与框架组装

本地 main.py 会初始化路径、单实例与运行资料目录，随后同步 custom_ok/ok 到安装框架，再初始化更新检查、诊断与账号服务，最后启动 SourceVersionOK(config)。custom_ok 的同步不是“缺失才复制”，内容不同时会覆盖框架文件。

安装框架组装以下对象：

| 对象 | 职责 |
|---|---|
| DeviceManager | 选择设备、目标窗口、捕获和输入后端 |
| FeatureSet | 读取 COCO 标注、裁剪模板、缩放、匹配和生成位置 |
| TaskExecutor | 提供当前帧与 OCR，执行一次性任务队列并轮询触发任务 |
| TaskManager | 根据配置里的模块／类路径加载任务，也支持用户 Python 任务 |
| App／HeadlessApp | 启动 GUI 或无界面模式；本地旧核心仍直接依赖部分 Qt 模块 |

任务公共能力沿 ExecutorOperation → FindFeature → OCR → BaseTask → TriggerTask 组合，包括点击、按键、长按、拖动、相对坐标、等待条件、模板、OCR、颜色统计、配置及暂停／退出。

BaseWWTask 再加入鸣潮登录、菜单、月卡、传送与游戏页面操作；CombatCheck 和 BaseCombatTask 加入战斗状态、切人及角色执行。**游戏规则不是 ok-script 自动生成的。**

本地源码规模为 src 下 278 个 Python 文件，其中 src/char 有 57 个。这个规模包含运行产品、历史任务、测试支持与专用业务，不能理解成 278 个独立功能。

### 2.2 当前 custom_ok 有项目耦合

自定义 TaskExecutor 直接导入 src.runtime.ocr_backend、vision_metrics、game_runtime_errors 和 src.evidence.service。当前安装的 TaskExecutor、windows_graphics 与原 wheel RECORD 哈希不同，并存在对应 custom_ok 文件；基础 task、PostMessage、Genshin、DeviceManager、窗口控制等抽查文件仍符合安装包记录。

因此不能把当前 custom_ok 整份复制出去，就视为已经得到干净的跨游戏运行核心。应将调度、输入所有权、帧服务与界面事件分离，账号完成证据和鸣潮错误语义留在应用／游戏层。

### 2.3 最新 ok-script 已经更接近通用基础设施

新上游有 ok/core、ok/task、ok/device、ok/ui/qt、ok/ui/web，旧 ok/gui 作为兼容入口。事件接口与 UI 分开，Qt 接主线程派发，Web 经 WebSocket 发送可序列化事件；提供无界面、Qt、FastAPI＋React 界面模式，以及任务驱动的 Web 扩展页。[S01]

这解决了核心与 UI 的耦合，也支持任务扩展；它仍没有自动统一不同游戏的 HUD、队伍、资源、镜头、地图与日常语义。新许可证的竞争产品限制也必须纳入选型。[S02]

## 3. 当前程序功能与模块全集

config.py 静态注册 **22 个一次性任务、7 个触发任务**。隐藏、过期和未注册状态必须区分；不能把全部文件都当成当前可用产品功能。

### 3.1 一次性任务：22 个注册项

下表类名对应 src/task 下同名 Python 文件；辅助模块注明目录。

| # | 功能与入口 | 相关模块 | 当前入口状态 |
|---|---|---|---|
| 1 | 每日任务 DailyTask | daily_observation、daily_reserve_policy、src/daily_timing；登录、月卡、活跃度、体力、邮件、战令、周任务 | 注册 |
| 2 | 刷 4C 声骸 FarmEchoTask | 共用战斗、声骸识别、副本／首领循环 | 注册 |
| 3 | 首领突破材料 WorldBossMaterialTask | world_boss_materials、world_boss_material_plan／progress | 注册 |
| 4 | 梦魇巢穴／残像聚落 NightmareNestTask | src/nightmare_nests | 注册但 visible=False；每日调用 |
| 5 | 无音区 TacetTask | tacet_targets、共用副本／战斗 | 注册但隐藏 |
| 6 | 凝素领域 ForgeryTask | DomainTask、forgery_targets、forgery_quota_plan／progress | 注册但隐藏 |
| 7 | 养成规划 MaterialPlannerTask | src/materials 的 catalog／model／vision／repository；材料与领奖账本 | 注册但隐藏；依赖已验证账号入口 |
| 8 | 模拟训练 SimulationTask | DomainTask | 注册但隐藏 |
| 9 | 多账号每日 MultiAccountDailyTask | runtime/account_selection_service、account_verification_service、login_flow_service；断点继续 | 注册 |
| 10 | 多账号每周乐园 MultiAccountWeeklyGardenTask | weekly_garden；共用账号周完成记录 | 注册 |
| 11 | 每周乐园 GardenTask | weekly_garden、小游戏／卡牌操作、周常积分复核；6000 分记录不代表奖励已领取 | 注册 |
| 12 | 悲鸣行动／无音危机 EventTask | 绕圈移动、奖励卡牌与商店操作；敌人由游戏自带自动战斗清理 | 注册；需手动进入活动地图 |
| 13 | 账号切换验证 TestAccountSwitchTask | 复用生产账号选择、身份匹配、登录／登出链路 | 注册但 visible=False |
| 14 | 自动深塔 AutoAbyssTask | abyss_team_planner、abyss_allocation、abyss_energy、abyss_cycle_progress | 注册 |
| 15 | 冥歌海墟 AutoSeaRuinsTask | sea_ruins、vision、tokens、recovery | 注册 |
| 16 | 周本 WeeklyBossTask | weekly_boss、weekly_boss_plan／progress | 注册 |
| 17 | 钢琴教学 PianoTeachingTask | piano | 注册但导航隐藏；旧活动 |
| 18 | 第二索拉 SecondSolTask | 周期按 F | 注册但导航隐藏；明确要求前台 |
| 19 | 若梦仍有回声 EchoesRemainTask | echoes_remain／support／continuation | 注册但导航隐藏；旧活动 |
| 20 | 群声共振模拟域 ResonanceSimulationTask | resonance_simulation；手动移动、技能栏战斗 | 注册但当前活动筛选排除 |
| 21 | 角色试用 CharacterTrialTask | character_trial、TrialGenericChar | 注册 |
| 22 | 天工寻物 TiangongTreasureTask | tiangong_treasure | 注册 |

### 3.2 触发任务：7 个注册项

| 功能 | 模块 | 补充 |
|---|---|---|
| 多人自动战斗 | AutoCombatTask | 核心常驻服务；保持用户开启意图 |
| 单人自动战斗 | SoloCombatTask | 实际一人队伍；默认关闭；与多人模式互斥 |
| 自动拾取 | AutoPickTask | UI 拾取提示与输入 |
| 自动登录 | AutoLoginTask | 默认关闭；登录路径涉及前台输入 |
| 自动剧情 | SkipDialogTask.AutoDialogTask、SkipBaseTask、story_skip | 页面／文字／对话选项识别 |
| 快速传送 | FastTravelTask、trigger_navigation | 默认关闭 |
| 鼠标防漂移 | MouseResetTask | 默认开启；部分条件下改变全局光标位置 |

### 3.3 代码存在，但不能计入当前完整功能

| 代码／卡片 | 实际状态 |
|---|---|
| FarmMapTask | 地图星标刷怪代码，当前未注册 |
| MergeEchoTask、FiveToOneTask | 合并／五合一代码，当前未注册；Daily 中仅发现 Merge import，未发现实际调用 |
| EnhanceEchoTask、ChangeEchoTask | 批量强化／修改声骸属性，注册配置明确注释掉 |
| KRLauncherSwitchTask | 文件序列切换方案已废弃，未注册 |
| DiagnosisTask | 独立诊断任务未注册；不代表后台诊断服务不存在 |
| 团团勇者大乱斗、梦构匣中 | GUI 手动留证卡片，未实现自动玩法 |
| CharacterCodeTab | 文件存在，当前 MainWindow 未挂载；不能称有可见角色代码编辑页 |

### 3.4 任务之外的产品能力

要复制当前定制版，除了战斗还要处理以下模块。只复制战斗类不能得到同一个完整产品。

| 能力 | 主要模块／目录 |
|---|---|
| 账号主数据、短名、身份、别名、槽位、序列与策略 | account_repository、account_profile_store、account_graph_store、account_identity、account_slots、sequence_repository、account_task_policy／state |
| 账号编辑、发布、重绑定、冲突保护 | account_config_editor、account_publish_service、account_rebind_service、config_integrity、account_change_lock、runtime/account_runtime_bootstrap |
| 游戏日／周周期、提醒、活动目录 | game_period、account_reminders、gui/activity_catalog |
| 每账号刷取队列、顺序与进度 | task/farming_task_queue、farming_task_scheduler；复用生产任务 |
| 完成证据、手动确认、截图、历史与导出 | evidence/model、repository、service、export、cycles；gui/CompletionCheckTab |
| 诊断录像、故障帧、事件、性能、ZIP 归档、上传与保留 | runtime/diagnostic_*、observability、vision_metrics、recording_policy |
| 运行资料目录初始化与迁移 | runtime/storage_bootstrap、storage_startup_ui、storage_handoff、diagnostic_storage；storage |
| 配置备份、验证、还原 | config_backup、secure_backup、account_config_bundle |
| LAN 更新、manifest、SHA-256、依赖兼容、退出后应用 | src/update 下 lan_service、lan_transport、lan_manifest、lan_apply、package_validation、dependency_compatibility、worker_process |
| 官方上游更新提示 | upstream_check |
| OCR 后端、同帧复用与性能 | runtime/ocr_backend、ocr_reuse |
| 共享场景状态 | scene/WWScene |
| 声骸检测模型 | globals、OpenVinoYolo8Detect／OnnxYolo8Detect；assets/echo_model/echo.onnx |
| 多语言与资源 | i18n/<lang>/LC_MESSAGES/ok.po 与 ok.mo、任务名称／配置翻译、图标与模板 |
| 打包与发布 | .github/workflows/build.yml；pyappify、版本与内容验证、安装包及源码更新包 |

当前 GUI 实际为任务、账号、完成检查、自动辅助、工具、设置六页，定义和组装分别见 src/gui/navigation_sections.py 与 custom_ok/ok/gui/MainWindow.py。

框架另外支持 ADB、模拟器／Nemu IPC、浏览器、离线 ImageCapture、Desktop Duplication、PyDirect、pynput、DoNothing 等后端；当前 okww config 主要配置 Windows。框架具备后端不等于本产品已验证全部设备。虚拟机／模拟器路线不符合本次用户约束，不作为推荐运行环境。

## 4. 自动战斗的实际原理与能力边界

核心机制是 **画面观测→战斗确认→角色规则→状态反馈→切人确认**。不是依靠大模型逐帧玩游戏，也不是单纯固定录制键鼠。

~~~mermaid
flowchart LR
    A[带时间戳的新帧] --> B[队伍与战斗 HUD]
    B --> C[头像 当前角色 技能状态]
    C --> D[角色规则与队伍轮转]
    D --> E[发键 长按 切人]
    E --> A
    C --> F[结束 死亡 结果交接 未知状态]
    F --> G[释放本任务输入 等待或恢复]
    G --> A
~~~

### 4.1 入口、战斗确认与角色识别

- AutoCombatTask 按 0.1 秒触发调度配置进入检查；进入战斗循环后的截图／动作节奏另由循环控制，不能直接说整个战斗固定为 10 FPS。
- CombatCheck 观察锁定图标、普通敌人红血条、Boss 血条和破盾提示，中键重新锁定；失去目标后有约 6 秒观察期。
- CharFactory 在队伍头像区域匹配注册模板；当前角色由槽位状态确认。窗口、账号等上下文变化会触发身份重新确认。
- BaseCombatTask 的 combat_once／perform_combat_rotation 同时供日常、副本和后台战斗使用。
- 正常结束、死亡、结果交接和截图／输入异常分开；不把缺帧或未知画面当成胜利。

### 4.2 状态识别是多种小方法组合

| 状态 | 当前方法 | 重写必须保留的语义 |
|---|---|---|
| E／声骸／解放冷却 | OCR 读取小数 CD，结合观察时间与缓存 | CD 估计与新视觉证据的关系 |
| 技能点亮 | 技能区域白色像素和 CD 判断 | 不同调用是否要求点亮 |
| 共鸣回路 | 区域像素与强化 E／重击提示模板 | 特定角色资源不能只靠统一阈值 |
| 协奏 | 元素颜色、圆环掩膜、形态学、连通域、轮廓与面积 | “满”及百分比估计不是单个通用 PNG |
| 专属形态 | 模板、颜色和条带检测 | 二段技能、浮空、印记、强化攻击 |
| 解放执行 | HUD 消失与回归、CD／状态变化 | 发键不直接等同于技能成功 |
| 动画冻结 | 记录／估算冻结区间并扣除 | 不是读取游戏引擎时钟 |

BaseChar.py 对 F 击破全局时停明确记录目前不能识别完整动画，计时存在限制。不能把现有机制描述为已精确覆盖所有卡肉、冻结和时停。

### 4.3 切人采用离散优先级与增益规则

SwitchPriority 基础值为 NO=0、LOW=100、NORMAL=200、HIGH=300、MUST=400，角色可返回偏移值。过滤不可用角色后，保留最高优先级候选，再依据角色类型和增益状态选择。

典型规则包含：排除阵亡／复活冷却角色；治疗者满协奏下场后的 16 秒切回锁定；有变奏时先完成尚未建立的辅助增益；无变奏时考虑切人 CD、增益剩余时间与上场顺序；主输出需要辅助续增益时让出驻场。

切人后观察槽位变化才记为成功；等待中协奏状态改变，会重新选择。它是手写优先规则，不是实时计算全队最优 DPS 的优化器。当前后台多人 AutoCombatTask 保留原多人轮转路径，部分前台任务的辅助准备预算不能泛化成全项目统一策略。

### 4.4 全角色支持意味着多少重写工作

本地 src/char 共 57 个 Python 文件、约 8056 行；CharFactory 注册 56 个 canonical 身份、65 个头像模板标签。注册数量不等于完整专属策略数量：aalto、lingyang、lumi、yangyang 直接使用 BaseChar；Chixia 实际沿用默认轮转；Youhu 主要增加大招选项修正。

| 规则类型 | 代表 | 迁移成本来源 |
|---|---|---|
| 简单辅助技能顺序 | Baizhi、Mortefi、Taoqi、Yuanwu | 技能、驻场与切人条件 |
| 有界技能优先循环 | JingRan、Hsin、Qiuyuan | 资源、动作阶段、普攻持续时间 |
| 协奏／增益准备 | Verina、ShoreKeeper、Mornye、Suisui | 增益起点、联动与切回锁定 |
| 多段技能／形态 | Hiyuki、Aemeath、Qingxiao、Lucilla | 专属状态、二段技能、成功确认 |
| 复杂角色联动 | Phoebe、Zani、Carlotta、Zhezhi、Cartethyia、Camellya | 队友身份、延奏窗口、长按、取消与特殊姿态 |

例如 Phoebe 约 849 行、Zani 629 行。把全部行为压成“角色名→按键序列”的单表会丢失联动与反馈。适合数据化的是简单技能顺序、资源与时长；复杂策略仍可保留独立可测试的策略代码。

### 4.5 当前有哪些防御／敌人理解能力

已发现中键锁定、血条／破盾检测、角色专用右键／跳跃／冲刺取消、浮空恢复、F 击破提示。守岸人的 auto_dodge 根据自身浮空和延奏增益状态连续右键，不能当成根据敌人前摇计算的通用闪避。

在所审阅核心中没有发现通用敌人分类、招式识别、黄圈弹反、无敌帧预测、战场空间规划或自动搜索最佳连招的系统。echo.onnx 用于声骸检测和拾取，不是核心轮转的敌人理解模型。

如果目标是“当前 okww 功能基本相同”，先重建规则闭环即可；如果目标包括更强的通用闪避、防反与复杂敌人战术，那是新增能力，不能计作已有功能复刻。

### 4.6 必须保留的执行与恢复契约

当前核心自动战斗将“用户开启意图”和“当前能否执行”分开。普通异常、截图失败、设备不可用或恢复失败不会保存关闭偏好；使用有上限的退避延迟，没有总错误次数后永久禁用。暂停、退出、用户关闭、死亡和结果交接仍有各自含义。

长按记录其原始后端，换后端后仍向原后端释放；未释放成功时不会继续叠加输入。单人与多人模式互斥，一次性任务在同一 executor 中优先执行，前台任务使用共用战斗循环。这套输入所有权和服务恢复语义应进入公共框架。

这里的“触发／后台任务”是调度类别，不代表 Windows 失焦窗口必然接受输入。

## 5. 素材能否复用，代码能否完全重写

**技术上可以。** 素材没有被绑定在某个不可替换的引擎里；PNG、COCO 标注与 ONNX 可以被新程序解析。达到同等稳定性还依赖原实现的状态语义、时序和真实验证。

### 5.1 素材实际规模与格式

| 内容 | 本次本地统计 |
|---|---|
| assets 总体 | 162 PNG、2 JSON、1 ONNX；44,158,229 bytes |
| COCO | 292 categories、292 annotations、166 image records |
| COCO 唯一源文件名 | 60 个；166 是记录数，不能说有 166 张不同截图 |
| 常见源尺寸 | 3840×2160、1920×1080，也有 1600×900、2560×1440 等 |
| echo.onnx | 37,907,104 bytes；声骸模型 |
| 材料模板 | 47 PNG 与 materials/catalog.json |
| 专项资源 | 活动、剧情、海墟、角色导入等图像 |

COCO annotation 将 image_id、category_id 与 bbox=[x,y,w,h] 关联。FeatureSet 从源图裁剪模板，缩放模板与坐标，使用 OpenCV matchTemplate。Labels 的字符串名称是代码与视觉包之间的契约。

素材还隐含搜索区域、锚点、宽高比与预处理。process_feature 会对特定提示做二值化等处理；只复制 PNG、丢掉 bbox／预处理／锚点，不能完整复现识别行为。

### 5.2 技术复用与发布授权是两个问题

技术上可以重新读取现有 PNG／JSON／ONNX，复用离线样本、角色身份别名和已观察行为作为需求索引。但是公开闭源产品不能仅凭“代码全部换了”推导出素材可直接分发。

- 项目 LICENSE.txt 是 AGPL-3.0。
- COCO 内 licenses 元数据声明 GPL-3.0；这只是元数据，不能视为每个图像／模型完整权利链的证明。
- assets 下没有发现独立宽松许可证和逐项来源授权。
- 游戏截图、图标自身另涉及游戏内容权利；自行采集可以避免复制项目作者素材，却不会自动获得商业分发游戏画面的许可。
- ONNX 只是模型格式；改格式／换推理库不会改变权重、训练代码和训练数据的授权来源。

保留闭源空间的方案是独立实现识别与策略，制作并记录自己的适配包来源，对需分发的图像／模型取得相应许可。直接搬用原项目代码／素材是另一条需要履行原许可的路线。

### 5.3 完全重写仍需重建的关键内容

1. 模板裁剪、坐标变换、锚点、缩放、掩膜和预处理。
2. HUD 观测、CD／资源／形态和身份确认。
3. 角色轮转、队友联动、增益与动画记账。
4. 可取消按键／长按，输入所有权与后端释放。
5. 战斗进入、结束、未知、死亡和结果交接。
6. 捕获／输入异常后的恢复与持久开启意图。
7. 日常、地图、领奖、账号和产品 UI 的完整流程。

现有 TestCD、TestForte、TestChar、TestFeatureSet、TestCharacterIdentityRecovery、TestAutoCombatRecovery、TestTrioCombatRecovery、TestCombatTaskModes、TestAllSoloRotations 可作为行为索引。截图和 mock 验证只覆盖部分识别／逻辑；连续录像与实际输入验证才能评价战斗稳定性。本次只阅读这些测试，没有运行。

## 6. 从鸣潮迁移原神，哪些层可以通用

**真正的通用单位是“核心＋游戏适配包”，不是“程序＋一套替换图片”。**

| 公共核心 | 游戏适配包 | 角色／队伍策略 |
|---|---|---|
| 帧采集、时间戳、输入后端与能力说明 | HUD 区域、锚点、键位与页面识别 | 动作优先级、连招与取消 |
| 模板、OCR、颜色和推理工具 | 队伍与角色身份、技能／资源解释 | 驻场、增益、联动、特殊形态 |
| 观测缓存、条件规则与可中断动作 | 战斗／死亡／领奖／复活语义 | 队伍构建的具体规则 |
| 单一输入所有者、暂停／恢复／退出 | 镜头、锁定、寻路与传送 | 针对副本／敌人的策略 |
| 调度、持久意图、记录与回放 | 每日／周任务图、活动和素材版本 | 回归样本与期望动作轨迹 |

公共动作可以包含普通攻击、重击、技能、爆发、切人、移动、视角；鸣潮的声骸、协奏、变奏／延奏和回路应属于鸣潮插件，不能成为每个游戏都必须实现的基类字段。

| 鸣潮假设 | 原神必须改写的内容 |
|---|---|
| 3 人队伍 | 4 人队伍、槽位与角色切换确认 |
| 中键锁定 | 无相同锁定机制；目标接近、朝向与镜头策略 |
| 共鸣／声骸／解放 | 元素战技／元素爆发；无声骸技能 |
| 协奏→变奏／延奏 | 能量、元素附着／反应、角色与装备增益 |
| 回路资源 | 体力、护盾、角色专属资源及攻击形态 |
| HUD 消失确认解放 | 各角色动画差异，以 CD／能量／形态等实际变化确认 |
| 延奏时刻估算 buff | 持续技能、快照、反应次序和增益窗口 |
| 现有鸣潮每日导航 | 原神地图、树脂、秘境、委托、传送与领奖 |

大世界导航还需要地图底图、区域坐标、相机／角色朝向、路径点、移动方式和脱困条件。BetterGI 的 Navigation／PathExecutor 通过小地图定位和路线动作闭环实现这些能力；任意游戏若没有稳定小地图，需要另一套视觉定位方案。换地图图像也不等于重新获得可通行路线与高度信息。[S05]

规则驱动适合当前目标。先覆盖明确队伍、固定副本与日常流程，比先训练一个端到端通用模型更容易验证。大模型可以用于离线解释与策略辅助，不宜在未经时延和可靠性验证时承担每次战斗发键决策。

## 7. 后台能力：截图、输入、持续渲染和隔离必须分开

后台可用至少需要：游戏仍产生新帧、采集器取得新帧、输入被游戏接受、自动化输入不影响主桌面。任一组件写着“后台”都不能代替这四个条件。

### 7.1 当前 okww 的实际边界

config.py 配置 PostMessage 与 WGC／BitBlt_RenderFull。WGC 使用 CreateForWindow 和 CreateFreeThreaded，取目标窗口；PostMessage 向指定 HWND 发送键鼠消息。它的 activate() 只发 WM_ACTIVATE／WA_ACTIVE，不是 SetForegroundWindow。

因此普通鸣潮战斗有可遮挡、低前台干扰的实现基础。但是：

| 已发现路径 | 实际行为 |
|---|---|
| BaseWWTask 的 PC 登录点击 | 经 send_input_click 前台输入边界 |
| MultiAccountDailyTask 登录／恢复 | force_foreground／bring_to_front |
| win32_login_input | SetForegroundWindow 与 SendInput |
| AutoAbyssTask 角色扫描／滚动等 | ensure_in_front |
| MouseResetTask | 特定条件下 SetCursorPos 恢复全局光标 |
| 安装框架窗口检查 | 最小化／移出屏幕导致 executor.pause |

本地 hwnd_window.py 明确提示“Paused because game window is minimized or out of screen!”。README 的“最小化后台”宣传不能覆盖这条真实路径；更可靠的初始条件是保持窗口在有效显示区域、未最小化、被其他窗口遮挡。

原神 GenshinInteraction 保存／恢复全局光标，部分点击和滚轮调用 BlockInput，滚轮涉及全局光标与 mouse.wheel，on_run 会把窗口置前。它不能直接作为严格零抢占的大世界动作战斗后端。

### 7.2 各条运行路线比较

| 路线 | 主桌面键鼠隔离 | 视角与完整操作 | 主要限制 | 理论定位 |
|---|---|---|---|---|
| 同会话 WGC＋PostMessage | 消息路径通常不移动主光标，但游戏与辅助流程可能干扰 | 取决于游戏如何处理消息与相对移动 | 焦点、Raw Input、最小化和实际页面兼容性 | 鸣潮轻量候选；难保证跨游戏 |
| 同会话 WGC＋SendInput／PyDirectInput | 没有独立隔离 | 通常较接近真实键鼠 | 输入进入当前会话输入流，前台工作被影响 | 不满足严格需求 |
| 同会话虚拟手柄 | 减少键鼠占用，不等于独立会话 | 需要完整手柄 UI／键位适配 | 焦点接收、设备共享、底层驱动维护 | 补充后端 |
| 虚拟显示器＋捕获 | 显示器不隔离输入 | 仍取决于原输入路径 | 新显示输出不等于第二输入桌面 | 显示辅助 |
| **原生 Child Session＋会话内执行器** | **Windows 会话边界** | 子会话内本地 SendInput 可操作与转视角 | 系统版本、GPU、游戏远程会话兼容性；一个活动连接子会话；用户组之间人工交接 | **桌面隔离优先验证方向** |
| 正式多用户 RDP／RDS | 有会话隔离 | 有条件 | Windows 版本／系统许可／CAL、GPU与游戏兼容性 | 更重的替代 |
| RDP Wrapper | 有会话边界 | 有条件 | 系统构建依赖、并发会话修改、Windows 更新与许可 | 不宜默认产品依赖 |
| Duo 多座席 | 项目提供独立桌面 | 有产品路径 | 运行时修改系统 DLL、共享手柄池、收费与系统版本 | 对照研究 |
| Sunshine／Moonlight／Apollo | 默认不额外隔离当前 Windows 会话 | 提供流传输和输入 | 虚拟屏与串流不能独立满足隔离 | 配套组件 |
| CreateDesktop 隐藏桌面 | 不是第二个并行活动 input desktop | 游戏持续渲染与输入不保证 | 一个 window station 同时只有一个活动输入桌面 | 不替代子会话 |
| Windows 服务／Session 0 | 与用户分离但无法正常承担交互游戏 | 不适合 | 官方交互服务限制 | 仅用于辅助管理 |

以上是源码／接口推导与公开项目证据，不是本机性能排名。

### 7.3 原生 Child Session 为什么最值得验证

Microsoft 从 Windows 8／Server 2012 起提供特殊的本机 loopback RDP 子会话：WTSEnableChildSessions 启用，RDP ActiveX 的 ConnectToChildSession 建立连接。一个系统最多一个 active and connected child session；绑定父会话，父会话结束时终止；没有通常的登录屏、锁屏和屏保。[S09]

BetterGI 桌面分身已经用这条路线在子会话运行原神与 BetterGI。源码导入 WTS 接口、使用 MsRdpClient10，设置 ConnectToChildSession，并通过任务计划 RunEx 指定子会话启动实例。该机制无需虚拟机，也无需 RDP Wrapper。[S06][S07]

该固定实现使用当前 Windows 用户，不是另建一份独立用户 profile。当前四用户账号组由人手动交接，各身份分别运行自己的子会话。若未来要求自动跨用户，可另研究同一个子会话内按不同 SID 启动游戏和执行器；微软 API 提供基础，但完整游戏环境尚未确认。详见补充报告第 4 节。

~~~mermaid
flowchart TB
    subgraph A[主 Windows 会话]
        U[控制界面 配置 状态]
        P[持续 RDP 连接 预览可隐藏]
    end
    subgraph B[独立 Child Session]
        G[原生游戏窗口]
        C[本会话 WGC 原始帧]
        R[观测 规则 自动化执行器]
        I[本会话 SendInput]
        G --> C --> R --> I --> G
    end
    U <-->|本机 IPC| R
    G --> P
~~~

关键是把执行器与游戏放在同一子会话。游戏可以在那个会话内部保持前台，而用户继续使用主会话。识别直接读子会话内原始截图，不必识别 RDP 压缩预览；自动化直接在子会话发送相对鼠标，不需要先经过主桌面转发。

BetterGI 的相对鼠标转发主要服务于用户手动操作预览窗，当前判断只适配原神。微软当前 IMsRdpExtendedSettings 另有 Windows 11 24H2 引入的 AllowRelativeMouseMode，以及本机 frame buffer redirection；可作为原生候选，不能断言 RDP 永远不支持相对鼠标，也不能当成鸣潮已验证。[S08]

BetterGI 文档固定分身 1920×1080、一次一个分身，原神／启动器有单实例限制；要求完整 Windows，支持要求为非家庭版，也记录部分家庭版能够运行。这不是本次微软 Child Sessions 文档对系统版本的完整枚举。隐藏预览与断开／注销会话不是同一操作。最小化、隐藏、连接保活、重连、异常退出和显卡实际加速都需要分别验证。

Child Session 提供的是 Windows 会话隔离，不是 CPU／GPU 隔离；部分游戏仍可能拒绝远程会话或不保持渲染，远程会话兼容性需要按游戏验证。

### 7.4 不建议作为默认方案的多座席与系统修改路线

Duo 官方 Known Issues 写明在 RAM 修改 termsrv.dll 以支持并发，修改 IddCx.dll／RdpIdd.dll 获取未压缩帧；并说明多个 native sessions 共享 XInput 设备池，物理手柄可能串会话。免费版的 30 Hz 与收费解锁是产品限制，不是本机性能实测。其公开仓库未提供足以复制实现的源码许可。[S15]

RDP Wrapper 自身采用 Apache 2.0，不代表其修改会话行为已经解决 Windows 的使用许可。按 build 依赖 INI／patch、与分身冲突和系统更新维护问题，使其不适合作为闭源商业框架的默认要求。[S16]

## 8. 捕获、输入、识别与规则组件选型

### 8.1 捕获：窗口与显示器目标不可混淆

| 项目／接口 | 实际用途 | 对需求的价值 |
|---|---|---|
| WGC／WinRT、Win32CaptureSample | 指定应用窗口或显示输出；异步帧池 | 同桌面被遮挡窗口、子会话原始帧的优先方向 |
| windows-capture | Rust／Python 的 WGC，当前也提供 DXGI | MIT；可替代自行写完整绑定 |
| PyWinRT | Python 访问 WinRT | MIT；独立 API 实现基础 |
| DXcam | 当前支持 dxgi／winrt 双后端，主要按输出实例取帧 | MIT；子会话显示输出或性能候选 |
| BetterCam | DXcam 派生，Desktop Duplication | MIT；较旧；不能按宣传 FPS 自动排第一 |
| MSS | 跨平台显示器截图 | MIT；诊断基线，不能凭裁剪恢复被遮挡窗口 |
| D3DShot | 旧 Desktop Duplication | 已归档，不宜新核心依赖 |
| PrintWindow／GDI | 窗口处理 WM_PRINT／WM_PRINTCLIENT 并渲染到 DC | 兼容路径，不能保证现代硬件加速游戏 |

DXGI Desktop Duplication 获取桌面输出，被遮住的游戏矩形里可能只是遮挡窗口。WGC 可针对 HWND，但 API 不能强迫游戏继续生成帧；游戏渲染、采集成功和新帧时效要分别确认。[S10][S11]

### 8.2 输入：SendInput、PostMessage、Raw Input 不是同一路径

- SendInput 将事件注入键鼠输入流，没有目标 HWND 参数；应放在独立会话内使用，不能把它描述为每窗口后台输入。执行器完整性级别须不低于目标游戏，否则受 UIPI 限制；子会话启动需处理权限一致性。
- PostMessage 投递窗口消息，游戏是否接受由其实现决定；不等于构造真实 WM_INPUT 设备数据。
- Raw Input／DirectInput 的后台接收通常需要游戏自身选择对应注册／协作模式；外部库无法仅凭名字改变这个契约。
- PyDirectInput 使用扫描码与 SendInput，可以改善部分游戏的输入兼容性，不能提供键鼠隔离。
- XInput 的焦点行为和共享设备池使“虚拟手柄＝通用失焦后台”无法成立。ViGEmBus 已退休／归档，vgamepad 的 Windows 后端仍依赖它；需要单独评价维护与替代驱动。[S12][S13]

MaaFramework 当前除 PostMessage／SendMessage 等方案外还有 BackgroundManagedKeyInput。源码中仍使用 SendInput，并维护按键域／热键逻辑；“Background”命名不能当成主桌面完全隔离。WithCursorPos 等输入方案也明确涉及光标位置。[S04]

### 8.3 视觉与推理：足够用的小组件优先

| 组件 | 许可信息 | 推荐用途 |
|---|---|---|
| OpenCV／OpenCvSharp | 当前 OpenCV Apache 2.0；OpenCvSharp 包须按发布版本核对 | 模板、颜色、几何、轮廓、地图特征 |
| RapidOCR／PaddleOCR | Apache 2.0 | UI 文字、CD、材料与奖励；按区域／页面需要调用 |
| ONNX Runtime | MIT | 轻量模型推理，Windows 有多种执行后端 |
| OpenVINO | Apache 2.0 | Intel 设备推理候选；不必与 ONNX Runtime 同时强制引入 |
| Ultralytics | AGPL／另有商业授权路线 | 自行训练检测模型前核对代码与权重许可；不适合未经核查直接塞入闭源产品 |

高频战斗应优先使用必要 HUD 区域、同一帧观测与简单特征，避免每个条件重复全图 OCR。OCR 或目标检测不需要负责所有状态；当前 okww 已说明少量规则与图像检测能够覆盖其多数轮转。

如以后加入敌人识别，需要独立数据集、标注、训练与误判评估。已有声骸检测模型不能直接替代敌人招式模型。

### 8.4 规则架构：借鉴 OneDragon 的可中断事件设计

OneDragon 用 StateRecorder 保存事件时间／值／互斥关系，条件树支持时间窗、值区间、AND／OR／NOT；ConditionalOperator 可按高优先级事件停止当前动作，OperationExecutor 的 stop 调用原子动作释放输入。[S17]

其闪避识别实际由 FlashClassifier 红／黄光图像分类，加系统 loopback 音频高通滤波与 WAV 模板相关性构成，再转为状态事件。不是一个已验证的统一视听神经网络。音频来自默认扬声器，未按游戏进程隔离；其他程序音频会进入样本。若迁移这类反应能力，音频来源也属于适配边界。

这套“观测事件→条件→可中断动作”比把每个角色完整动作写进不可抢占的长函数，更适合日后接入闪避、防反。可以独立实现这种设计；GPL 源码不能直接复制后声明为闭源。

BehaviorTree.CPP（MIT）与 py_trees（BSD）可作规则组件候选，但当前任务不要求为简单规则引入一套庞大行为树编辑器。先用有限状态机、条件规则与可取消动作满足实际能力，复杂度出现后再选组件。

## 9. 外部项目对照：哪些值得参考、哪些不宜作为核心

| 项目 | 本次检查深度 | 可参考的部分 | 限制／选型意见 |
|---|---|---|---|
| ok-script | 安装源码、部分 RECORD、新上游架构与许可证 | CV 运行时、任务、设备、UI 分离 | 版本与许可证必须分开；不默认用于竞争商业框架 |
| 原版 okww | 固定提交 config；本地完整业务与战斗 | 鸣潮角色／HUD／任务契约 | AGPL；不是通用敌人 AI |
| ok-ww-enhanced | README、固定 config、LICENSE | 日常任务与日志改进对照 | 仍是 okww 派生，AGPL；不是独立通用底座 |
| BetterGI | 战斗、条件解析、输入、导航及 Child Session 源码 | 原神技能规则、小地图路线、原生桌面分身 | GPL；作为设计与验收参考很强 |
| OneDragon／绝区零 | 状态、条件、执行器、闪避观测源码 | 事件抢占、动作释放、声明式条件 | GPL；绝区零资源／模型不通用 |
| GIA | README、GitHub 状态、许可证元数据 | 早期原神战斗与任务思路 | 已归档；README 与许可元数据有差异，使用前按实际 LICENSE 核实 |
| tignioj/minimap | README、目录、FightController、LICENSE | 视觉定位、地图／路线／GUI 分包 | 2025-02-25 停维；GPL 文件与 README 禁商声明存在需厘清的授权表述 |
| Airtest | README、LICENSE、Windows 后端源码 | 图像自动化测试、回放与报告 | Apache 2.0；当前 Windows 后端有前台／全局键鼠操作，不解决隔离 |
| Yap | README | 高效拾取提示识别、区域处理思路 | 专项拾取器；非完整战斗框架，未完成发布许可评估 |
| MaaFramework | Pipeline、Windows API、输入／伪最小化／自定义动作源码、LICENSE | 数据化 UI 任务、识别、控制器与开发生态 | LGPL；战斗必须自定义，控制器不能保证游戏接受后台输入 |
| WGC／PyWinRT 组件 | README、示例源码、许可及微软 API | 独立后台窗口／子会话采集 | MIT 项目优先；运行条件仍需实测 |
| DXcam／BetterCam／MSS／D3DShot | README、机制与维护状态 | 显示输出捕获与诊断 | 不能等同于遮挡窗口捕获；D3DShot 已归档 |
| Sunshine／Moonlight／Apollo | README、Sunshine Windows 捕获／输入源码、许可 | 串流、远程预览、虚拟屏与设备 | GPL；默认没有额外会话隔离 |
| Virtual Display Driver | README、许可／状态 | 无物理屏显示输出 | MIT；不独立解决输入 |
| Duo | README、Setup Guide、Known Issues | 无 VM 多座席产品对照 | 系统内存 patch、商业限制与源码许可不明，不作默认依赖 |
| RDP Wrapper | README、许可、BetterGI 使用文档 | 并发会话方案对照 | build 依赖与 Windows 许可问题，优先级低 |
| vgamepad／ViGEmBus | README、许可／归档状态、XInput 官方文档 | 手柄输入候选 | 底层退休和焦点／共享问题 |
| PyAutoGUI／PyDirectInput | README／许可，后者机制 | 普通自动化和游戏键鼠兼容性 | 同会话使用不能隔离前台 |
| OpenCV／RapidOCR／PaddleOCR／ORT／OpenVINO | README／许可证 | 独立视觉核心组件 | 按需选择；模型本身另核许可 |
| Ultralytics | LICENSE | 训练／检测生态对照 | AGPL 或商业授权；模型来源要追踪 |
| BehaviorTree.CPP／py_trees | README 与许可声明 | 异步动作、状态与行为组合 | MIT／BSD 候选，不必初期全部引入 |

MAA 类任务框架与菜单／日常自动化很匹配，但“能描述任务图”不等于“已经拥有动作游戏实时轮转”。Maa 的 CustomAction／CustomRecognition 提供接入点，应把战斗作为专用执行服务，而不是给每次普攻堆一层慢速 OCR 节点。[S03]

Maa 还包含伪最小化支持：恢复窗口而不激活等方式维持捕获。它不是强迫真正最小化的所有游戏继续渲染，也与本地 okww 的窗口范围检查不自动兼容。

## 10. 闭源与商业化：许可证对路线的实际影响

商业化和闭源不是同一条件。GPL／AGPL 并非一概禁止收费，但分发衍生程序、网络服务等情形会有源码与许可证义务，不能直接用相关代码形成闭源产品。应按实际版本的许可文本决定复用范围。

| 对象 | 实际许可／证据 | 对目标的影响 |
|---|---|---|
| 本地 okww | LICENSE.txt：AGPL-3.0 | 直接衍生与闭源目标冲突 |
| 安装 ok-script 1.0.190 | dist-info 完整 LICENSE 为 AGPL；classifier 却写 MIT | 不能只看 classifier；以完整许可核查 |
| 新 ok-script 固定提交 | Apache 2.0＋Commons Clause＋附加条款 | 允许部分闭源／商业内嵌使用，但限制框架本身或主要基于它的竞争产品；要求显著归属链接 |
| BetterGI、OneDragon | GPL-3.0 | 可参考设计；复制衍生源码需要履行 GPL |
| MaaFramework | LGPL-3.0 | 闭源上层存在可行使用方式；动态链接、替换／重链接、通知及库修改源码等义务要满足 |
| 本地 Fluent Widgets 1.8.3 | 包 metadata：GPLv3 | 不能因框架许可变化就直接闭源 UI；需独立 UI／单独商业授权 |
| PySide6 | LGPL／GPL 多许可 | 可考虑 LGPL 合规方式；具体模块、打包和替换条件需核查 |
| MIT／Apache／BSD 视觉组件 | 见各项目 LICENSE | 更适合作为独立核心候选，仍保留通知与各自义务 |
| 现有素材／权重 | 无逐项完整独立许可；COCO 有 GPL 元数据 | 独立采集／制作并核清分发权，不能靠代码重写消除问题 |

**不能把 GPL 软件改成子进程或 IPC，就自动认定整个组合可闭源。** 独立实现微软公开接口与通用算法，和复制 GPL 产品源码，是不同路线。

新 ok-script 的条款与用户想公开发布“广泛适用的自动化框架”高度相关；应在选它之前明确是否构成条款中的竞争产品。不能把它标成无限制的标准 Apache 2.0。[S02]

## 11. 三条重建路线与推荐技术组合

| 路线 | 功能接近速度 | 跨游戏能力 | 闭源空间 | 后台问题 | 判断 |
|---|---|---|---|---|---|
| A：沿用／改造 ok 及 okww | 现有鸣潮积累最多 | 要拆业务与框架耦合 | 旧 AGPL、新附加许可与 UI 都要处理 | 仍需独立输入／会话方案 | 自用或持续开源更合适 |
| B：MaaFramework＋独立战斗核心 | 日常 UI 与任务图可复用基础设施 | 控制器／识别工具通用，游戏规则独立 | 满足 LGPL 时有闭源上层路线 | 同样需 Child Session 或游戏特定输入 | 折中候选 |
| C：独立 Windows 核心＋游戏包 | 初期重写工作最多 | 边界最清楚 | 许可来源最可控 | 原生 Child Session 与消息后端自行适配 | **最匹配本次长期目标** |

### 11.1 推荐组合

面向 Windows 原生发布，可优先评估 **C#／.NET 控制界面与会话宿主＋同会话执行器＋OpenCV／OpenCvSharp＋ONNX Runtime＋按需 OCR**。C# 与 WPF／WinForms／COM 的组合比较方便承接 RDP ActiveX 和 Task Scheduler；这不要求把 BetterGI 的 GPL 代码移植进来。

若现有团队更熟悉 Python，也可以 Python 规则／视觉核心配一个小型原生会话宿主，WGC 经 MIT 组件或 WinRT 绑定使用。是否两种语言要依据维护成本决定，不必为了架构图强行拆多个服务。规则执行和视觉尽量在同一个子会话执行器完成。

通用核心至少需要：

- 新帧服务与观测时间，模板／OCR／模型工具。
- 输入能力边界：同会话消息输入与会话内真实输入分开说明。
- 规则条件、动作取消、按键释放和单一输入所有者。
- 战斗服务、任务流程与持久开启意图。
- 游戏包版本、角色策略、页面／导航／素材映射。
- 日志、录像样本、回放验证、配置及发布机制。

Maa 可用于菜单、领取、材料与任务图，但无需同时引入两套争用截图和输入的调度器。若使用它，应明确战斗期间谁持有输入、谁产出帧、如何交回任务流程。

### 11.2 建议先验证的运行路线顺序

1. **原生 Child Session**：先验证原神公开路线在目标系统的行为，再确认鸣潮启动、渲染、截图、键鼠和相对视角是否正常。游戏与执行器均在当前身份的子会话内；序列结束后由用户手动切换 Windows 用户，自动跨 SID 启动不作为当前前置条件。
2. **鸣潮同会话 WGC＋PostMessage**：作为低开销方式，对战斗、菜单、领奖、登录、深塔等分别确认；不能把普通战斗成功推广成全部任务无干扰。
3. **虚拟手柄／虚拟显示器配套**：有实际兼容缺口时再评估；不是自动替代会话隔离。
4. **正式多用户环境／Duo／RDP Wrapper**：作为限制下的对照，不优先成为产品安装前提。

这些是后续验证建议；本次没有尝试启用任何系统路线。

## 12. 进入实现前，最小而有判断力的验证

不需要先写完整程序。先回答两个会决定架构是否成立的问题：**目标游戏能否在隔离会话里持续运行并接受输入；同一套公共运行时能否承载两个独立游戏适配包。**

| 阶段 | 验证内容 | 能据此判断什么 |
|---|---|---|
| 运行环境 | 系统版本、子会话创建、原神／鸣潮启动、有效新帧、相对视角、主桌面键鼠、隐藏预览 | 无 VM 会话路线是否实际可用 |
| 基础识别 | 已有／自制离线截图的队伍、CD、资源、战斗／结果状态 | 新识别实现能否解释同一画面 |
| 连续回放 | 录像中的观测→规则→按键轨迹、状态切换、技能成功、切人确认 | 是否重现时序与决策；静态截图做不到 |
| 少量角色闭环 | 输出、辅助、治疗各一类；原神一支明确队伍 | 公共核心与游戏语义的边界是否成立 |
| 小范围日常 | 进入副本→战斗→领奖→重复／退出 | 战斗与日常输入交接能否正常工作 |
| 故障场景 | 失帧、游戏失联、暂停、停止、死亡、退出、恢复 | 是否释放输入并保留正确开启意图 |

评价时记录实际帧新鲜度、捕获／识别／决策／输入各段延迟、按键执行成功率、切人确认、任务完成率与前台干扰。30 Hz 一帧约 33 ms、60 Hz 约 17 ms 只是时间尺度，不是对任何项目的实测反应承诺。

完整复刻的主要成本会落在角色机制、页面／地图语义和长期回归样本，而不是把输入 API 包装成几个函数。规则、素材和工作流都应该按游戏版本维护。

## 13. 本地关键证据定位

| 结论 | 源码定位 |
|---|---|
| 版本与捕获／输入配置 | [config.py](<E:/AI work/ok-wuthering-waves-master/config.py:22>)；输入 230、捕获 231、任务注册 287 起 |
| 多人与单人后台入口 | [AutoCombatTask.py](<E:/AI work/ok-wuthering-waves-master/src/task/AutoCombatTask.py:14>)；[SoloCombatTask.py](<E:/AI work/ok-wuthering-waves-master/src/task/SoloCombatTask.py:4>) |
| 持久意图、恢复 | AutoCombatTask.py：68、131、203 |
| 战斗状态与血条 | [CombatCheck.py](<E:/AI work/ok-wuthering-waves-master/src/combat/CombatCheck.py:157>)；304、337、352 |
| 公共循环、输入释放、切人 | [BaseCombatTask.py](<E:/AI work/ok-wuthering-waves-master/src/task/BaseCombatTask.py:207>)；97、183、596、692、796、946 |
| CD／协奏与像素状态 | BaseCombatTask.py：333、571、1077、1451、1500 |
| 角色动作、优先级与冻结 | [BaseChar.py](<E:/AI work/ok-wuthering-waves-master/src/char/BaseChar.py:220>)；21、631、777、786、858、1084 |
| 身份与角色注册 | [CharFactory.py](<E:/AI work/ok-wuthering-waves-master/src/char/CharFactory.py:59>)；186 |
| 守岸人专用 auto_dodge | [ShoreKeeper.py](<E:/AI work/ok-wuthering-waves-master/src/char/ShoreKeeper.py:50>) |
| 视觉标签与预处理 | [Labels.py](<E:/AI work/ok-wuthering-waves-master/src/Labels.py:4>)；[process_feature.py](<E:/AI work/ok-wuthering-waves-master/src/task/process_feature.py:4>) |
| COCO 与许可元数据 | [coco_annotations.json](<E:/AI work/ok-wuthering-waves-master/assets/coco_annotations.json:10>) |
| 登录前台操作 | [BaseWWTask.py](<E:/AI work/ok-wuthering-waves-master/src/task/BaseWWTask.py:1405>)；[win32_login_input.py](<E:/AI work/ok-wuthering-waves-master/src/win32_login_input.py:221>) |
| 多账号置前 | [MultiAccountDailyTask.py](<E:/AI work/ok-wuthering-waves-master/src/task/MultiAccountDailyTask.py:2311>)；1666 |
| 深塔置前 | [AutoAbyssTask.py](<E:/AI work/ok-wuthering-waves-master/src/task/AutoAbyssTask.py:1822>)；1122、1918、1956、1975 |
| 全局光标恢复 | [MouseResetTask.py](<E:/AI work/ok-wuthering-waves-master/src/task/MouseResetTask.py:39>) |
| 最小化暂停 | [.venv/ok/hwnd_window.py](<E:/AI work/ok-wuthering-waves-master/.venv/Lib/site-packages/ok/device/capture_methods/hwnd_window.py:283>) |
| PostMessage 的消息激活 | [.venv/ok/post_message.py](<E:/AI work/ok-wuthering-waves-master/.venv/Lib/site-packages/ok/device/interaction_methods/post_message.py:125>) |
| 原神 BlockInput／鼠标／置前 | [.venv/ok/genshin.py](<E:/AI work/ok-wuthering-waves-master/.venv/Lib/site-packages/ok/device/interaction_methods/genshin.py:75>)；100、141、306 |
| 定制 executor 的项目依赖 | [custom TaskExecutor.py](<E:/AI work/ok-wuthering-waves-master/custom_ok/ok/task/TaskExecutor.py:199>)；294、360、572、686 |

## 14. GitHub 与官方来源

### 核心源码与方案

- [S01] [ok-script 固定提交架构](https://github.com/ok-oldking/ok-script/blob/428bcd563292ac6451c84c0222e6b790d468215f/docs/architecture.md)、[README](https://github.com/ok-oldking/ok-script/blob/428bcd563292ac6451c84c0222e6b790d468215f/README.md)。
- [S02] [ok-script 固定提交完整许可](https://github.com/ok-oldking/ok-script/blob/428bcd563292ac6451c84c0222e6b790d468215f/LICENSE.txt)。
- [S03] [MaaFramework Pipeline 协议](https://github.com/MaaXYZ/MaaFramework/blob/8963191215ca49d6b037802acd07d20a4213160a/docs/en_us/3.1-PipelineProtocol.md)、[CustomAction](https://github.com/MaaXYZ/MaaFramework/blob/8963191215ca49d6b037802acd07d20a4213160a/source/MaaFramework/Task/Component/CustomAction.cpp)、[LGPL 许可](https://github.com/MaaXYZ/MaaFramework/blob/8963191215ca49d6b037802acd07d20a4213160a/LICENSE.md)。
- [S04] [Maa Windows 后端定义](https://github.com/MaaXYZ/MaaFramework/blob/8963191215ca49d6b037802acd07d20a4213160a/include/MaaFramework/MaaDef.h)、[BackgroundManagedKeyInput](https://github.com/MaaXYZ/MaaFramework/blob/8963191215ca49d6b037802acd07d20a4213160a/source/MaaWin32ControlUnit/Input/BackgroundManagedKeyInput.cpp)、[伪最小化](https://github.com/MaaXYZ/MaaFramework/blob/8963191215ca49d6b037802acd07d20a4213160a/source/MaaWin32ControlUnit/Screencap/PseudoMinimizeHelper.cpp)。
- [S05] BetterGI：[AutoFightTask](https://github.com/babalae/better-genshin-impact/blob/8a4db294362c682ca709ebeef205f77fca4d575e/BetterGenshinImpact/GameTask/AutoFight/AutoFightTask.cs)、[ConditionEvaluator](https://github.com/babalae/better-genshin-impact/blob/8a4db294362c682ca709ebeef205f77fca4d575e/BetterGenshinImpact/GameTask/AutoFight/Script/ConditionEvaluator.cs)、[Navigation](https://github.com/babalae/better-genshin-impact/blob/8a4db294362c682ca709ebeef205f77fca4d575e/BetterGenshinImpact/GameTask/AutoPathing/Navigation.cs)、[PathExecutor](https://github.com/babalae/better-genshin-impact/blob/8a4db294362c682ca709ebeef205f77fca4d575e/BetterGenshinImpact/GameTask/AutoPathing/PathExecutor.cs)、[输入后端](https://github.com/babalae/better-genshin-impact/blob/8a4db294362c682ca709ebeef205f77fca4d575e/BetterGenshinImpact/Core/Input/Backends/Win32/Win32InputBackend.cs)。
- [S06] BetterGI [桌面分身文档](https://www.bettergi.com/feats/command/session.html)、[分身窗口说明](https://www.bettergi.com/feats/command/session-window.html)。
- [S07] BetterGI [ChildSessionNativeMethods](https://github.com/babalae/better-genshin-impact/blob/8a4db294362c682ca709ebeef205f77fca4d575e/BetterGenshinImpact/Service/ChildSession/ChildSessionNativeMethods.cs)、[RdpActiveXHost](https://github.com/babalae/better-genshin-impact/blob/8a4db294362c682ca709ebeef205f77fca4d575e/BetterGenshinImpact/View/Controls/ChildSession/RdpActiveXHost.cs)、[子会话进程启动](https://github.com/babalae/better-genshin-impact/blob/8a4db294362c682ca709ebeef205f77fca4d575e/BetterGenshinImpact/Service/ChildSession/ChildSessionProcessLauncher.cs)、[原神相对鼠标转发](https://github.com/babalae/better-genshin-impact/blob/8a4db294362c682ca709ebeef205f77fca4d575e/BetterGenshinImpact/Service/Instance/MessageHandlers/RelativeMouseMessageHandler.cs)。
- [S08] Microsoft [IMsRdpExtendedSettings.Property](https://learn.microsoft.com/en-us/windows/win32/termserv/imsrdpextendedsettings-property)。
- [S09] Microsoft [Child Sessions](https://learn.microsoft.com/en-us/windows/win32/termserv/child-sessions)、[WTSEnableChildSessions](https://learn.microsoft.com/en-us/windows/win32/api/wtsapi32/nf-wtsapi32-wtsenablechildsessions)、[WTSGetChildSessionId](https://learn.microsoft.com/en-us/windows/win32/api/wtsapi32/nf-wtsapi32-wtsgetchildsessionid)。
- [S10] Microsoft [WGC](https://learn.microsoft.com/en-us/windows/uwp/audio-video-camera/screen-capture)、[Desktop Duplication](https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/desktop-dup-api)、[DXGI 状态与遮挡](https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/dxgi-status)。
- [S11] Microsoft [PrintWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-printwindow)。
- [S12] Microsoft [SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)、[PostMessageW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-postmessagew)、[Raw Input](https://learn.microsoft.com/en-us/windows/win32/inputdev/about-raw-input)、[DirectInput cooperative level](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/ee417921(v=vs.85))。
- [S13] Microsoft [XInputEnable](https://learn.microsoft.com/en-us/windows/win32/api/xinput/nf-xinput-xinputenable)。
- [S14] Microsoft [Desktops](https://learn.microsoft.com/en-us/windows/win32/winstation/desktops)、[Window Stations](https://learn.microsoft.com/en-us/windows/win32/winstation/window-stations)、[Interactive Services](https://learn.microsoft.com/en-us/windows/win32/services/interactive-services)。
- [S15] Duo [README](https://github.com/DuoStream/Duo)、[Known Issues](https://github.com/DuoStream/Duo/wiki/Known-Issues)、[Setup Guide](https://github.com/DuoStream/Duo/wiki/Setup-Guide)。
- [S16] [RDP Wrapper](https://github.com/stascorp/rdpwrap)、[维护分支](https://github.com/sebaxakerhtc/rdpwrap)、[BetterGI RDP 教程](https://www.bettergi.com/tutorial/rdp.html)。
- [S17] OneDragon [状态记录](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon/blob/9633c6a68e42ee7500cdf3fc9677dde2b51f1fe2/src/one_dragon/base/conditional_operation/state_recorder.py#L27)、[条件树](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon/blob/9633c6a68e42ee7500cdf3fc9677dde2b51f1fe2/src/one_dragon/base/conditional_operation/state_cal_tree.py#L64)、[事件抢占](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon/blob/9633c6a68e42ee7500cdf3fc9677dde2b51f1fe2/src/one_dragon/base/conditional_operation/operator.py#L187)、[动作停止](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon/blob/9633c6a68e42ee7500cdf3fc9677dde2b51f1fe2/src/one_dragon/base/conditional_operation/operation_executor.py#L81)、[视听闪避观测](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon/blob/9633c6a68e42ee7500cdf3fc9677dde2b51f1fe2/src/zzz_od/auto_battle/auto_battle_dodge_context.py#L90)。

### 其他检查的仓库

| 类别 | 来源 |
|---|---|
| 鸣潮基础与改版 | [okww](https://github.com/ok-oldking/ok-wuthering-waves/tree/b210632a251371cc0bbb1d0e28ce16ff35657824)、[ok-ww-enhanced](https://github.com/zzc-tongji/ok-ww-enhanced/tree/310d8d9428ec78e62f11f429de75baf47d189add) |
| 原神旧方案 | [GIA](https://github.com/infstellar/genshin_impact_assistant/tree/9d3357bbe6c50b5aff410d5695da4bd52e0dc26e)、[minimap](https://github.com/tignioj/minimap/tree/dea82f9387fb7b3196d5b83dbcd1b5814ed78387)、[Yap](https://github.com/Alex-Beng/Yap) |
| 自动化测试 | [Airtest](https://github.com/airtestproject/Airtest)、[Windows 后端](https://github.com/airtestproject/Airtest/blob/master/airtest/core/win/win.py) |
| WGC | [windows-capture](https://github.com/NiiightmareXD/windows-capture)、[Win32CaptureSample](https://github.com/robmikh/Win32CaptureSample)、[PyWinRT](https://github.com/pywinrt/pywinrt) |
| 输出捕获 | [DXcam](https://github.com/ra1nty/DXcam)、[BetterCam](https://github.com/RootKit-Org/BetterCam)、[MSS](https://github.com/BoboTiG/python-mss)、[D3DShot](https://github.com/SerpentAI/D3DShot) |
| 输入 | [vgamepad](https://github.com/yannbouteiller/vgamepad)、[ViGEmBus](https://github.com/nefarius/ViGEmBus)、[PyDirectInput](https://github.com/learncodebygaming/pydirectinput)、[PyAutoGUI](https://github.com/asweigart/pyautogui) |
| 串流与虚拟屏 | [Sunshine](https://github.com/LizardByte/Sunshine)、[Moonlight Qt](https://github.com/moonlight-stream/moonlight-qt)、[Apollo](https://github.com/ClassicOldSong/Apollo)、[Virtual Display Driver](https://github.com/VirtualDrivers/Virtual-Display-Driver) |
| 视觉推理 | [OpenCV](https://github.com/opencv/opencv)、[RapidOCR](https://github.com/RapidAI/RapidOCR)、[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)、[ONNX Runtime](https://github.com/microsoft/onnxruntime)、[OpenVINO](https://github.com/openvinotoolkit/openvino)、[Ultralytics](https://github.com/ultralytics/ultralytics) |
| 规则组件 | [BehaviorTree.CPP](https://github.com/BehaviorTree/BehaviorTree.CPP)、[py_trees](https://github.com/splintered-reality/py_trees) |
