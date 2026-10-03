# 每日任务世界首领突破材料 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> 当前环境未列出上述执行技能。实施时使用可用的项目技能和本计划逐项推进；执行方式需遵守当时的用户与Agent指令，本计划不授权启动子Agent或开始修改程序。

**Goal:** 每日任务优先按三个世界首领累计领奖目标刷突破材料，全部达标后跟随账号既有体力用途。

**Architecture:** 以FarmEchoTask的讨伐强敌执行流程为基础，材料任务用独立实例调用共享单轮刷取并统一处理领奖。目标规则和领奖记录借用周本模式、使用现有账号原子运行状态服务。DailyTask的正常体力与局部补跑统一调度首领材料及后续用途。

**Tech Stack:** Python 3.12、ok-script、PySide6、现有ConfigIntegrityService和账号UUID、既有OCR与图像特征、unittest。

**Spec:** [完整设计](../specs/2026-10-03-world-boss-materials-design.md)。状态：未实施；基线1.92.02 / b5edc564。

代码框中的省略号仅声明未来接口签名，不是待填实现；每个接口的行为、测试及实施步骤在对应任务中定义。进入实施阶段前先阅读完整设计。

## Global Constraints

- 只统计成功领取奖励的次数；材料产出数量不参与判断。
- 三个首领按1→2→3执行，计数跨日跨周保留；全部达标后跟随账号既有体力用途。
- 单账号每日与多账号每日共享账号UUID、配置和累计进度。
- 复用4C讨伐强敌流程，不复制整个战斗循环；原声骸实例不领取体力材料奖励。
- 材料模式每轮只领一次单倍奖励；未知领取结果保留pending，禁止重复消费。
- 自动战斗保持启用意图；前台与后台不能同时发送战斗输入。
- 所有截图录像证据使用现有okww监控室存储服务。
- Python使用本机项目虚拟环境；该恢复工作树的可用解释器为 `E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe`。
- NAS仅使用 `\\192.168.3.173\羲火君 共享给我\AI诊断`。
- 实施时在同一功能版本中同步config.py、README和更新日志；当前拟1.93.00，按实际实施基线校正。

## 文件职责

| 文件 | 创建/修改与职责 |
|---|---|
| `src/task/world_boss_materials.py` | 创建；首领目录、稳定ID与4C场景映射 |
| `src/task/world_boss_material_plan.py` | 创建；三目标验证和优先级选择 |
| `src/task/world_boss_material_progress.py` | 创建；独立领奖账本、待核验与恢复合并 |
| `src/task/WorldBossMaterialTask.py` | 创建；材料模式、领奖与目标循环 |
| `src/task/FarmEchoTask.py` | 修改；共享单轮刷取，材料模式处理钩子、名称核对 |
| `src/task/DailyTask.py` | 修改；统一清体力入口、活跃度补跑、信息与完成记录 |
| `src/gui/WorldBossMaterialPlanWidget.py` | 创建；三目标控件及进度核对 |
| `src/gui/AccountConfigTab.py` | 修改；账号/模板编辑与体力分组 |
| `src/account_field_metadata.py` | 修改；中文标签与帮助 |
| `src/config_integrity.py` | 修改；受保护字段、类型、增量默认值、目标校验 |
| `src/account_repository.py` | 修改；旧账号和模板读取默认值 |
| `src/account_config_bundle.py` | 修改；进度导出及恢复合并 |
| `src/gui/CompletionCheckTab.py` | 修改；目标进度/待核验显示 |
| `config.py` | 修改；隐藏子任务注册及最终版本号 |
| `README.md`、`更新日志.md` | 修改；功能说明和版本同步 |
| `tests/TestWorldBossMaterialPlan.py` | 创建；规则、进度、合并 |
| `tests/TestWorldBossMaterialTask.py` | 创建；领奖、同次切目标、回调失败 |
| `tests/TestWorldBossMaterialUI.py` | 创建；控件、模板与可见状态 |
| `tests/TestFarmEcho.py`、`tests/TestDailyActivityFlow.py` | 修改；共享流程与每日分支回归 |
| 现有账号完整性、导入、体力、自动战斗测试 | 添加相关联动用例，沿用生产入口 |

不改造账号切换方法；若实施发现必须调整生产切换链路，同步TestAccountSwitchTask并保留A1→A3→A4默认顺序。

## 统一接口

实现时保持以下契约；这些是设计接口，当前尚未创建。

```python
# world_boss_materials.py
@dataclass(frozen=True)
class WorldBossTarget:
    key: str
    name: str
    aliases: tuple[str, ...]
    farm_profile: str
    ordinal_hint: int

WORLD_BOSS_TARGETS: tuple[WorldBossTarget, ...]

# world_boss_material_plan.py
MATERIAL_TARGETS = 'World Boss Material Targets'
def material_plan(tasks: Mapping[str, Any]) -> list[dict[str, Any]]: ...
def choose_material_target(rows: list[dict[str, Any]],
                           counts: Mapping[str, int]) -> tuple[str, int] | None: ...
def material_plan_revision(rows: list[dict[str, Any]]) -> str: ...

# world_boss_material_progress.py
class WorldBossMaterialProgress:
    def __init__(self, service, profile_id: str): ...
    def counts(self) -> dict[str, int]: ...
    def pending(self) -> dict[str, dict]: ...
    def begin(self, boss: str, cost: int, revision: str) -> str: ...
    def resolve(self, event_id: str, received: bool) -> None: ...
    def correct(self, boss: str, count: int) -> None: ...
def preserve_material_progress(incoming: dict, current: dict) -> dict: ...

# FarmEchoTask.py
@dataclass(frozen=True)
class FarmCycleResult:
    combat_entered: bool
    revived: bool
    echo_picked: bool
def farm_cycle(self, *, pickup_echo: bool = True) -> FarmCycleResult: ...

# WorldBossMaterialTask.py
@dataclass(frozen=True)
class MaterialRunResult:
    claimed: int
    spent: int
    status: str  # complete / resource_shortfall / plan_disabled

def run_for_profile(self, profile_id: str, read_tasks: Callable[[], Mapping],
                    guard: Callable[[], None], service, *,
                    activity_ready: bool | None, used_stamina: int | None
                    ) -> MaterialRunResult: ...

# DailyTask.py
def _run_profile_stamina(self, config: Mapping, *,
                         activity_ready: bool | None,
                         used_stamina: int | None) -> None: ...
```

材料任务错误与pending通过异常交给现有每日异常链路；不把未知结果返回为正常complete。`None`目标只代表没有启用/未达标目标，调用者依据配置区分关闭与已达标。

## Task 1：三目标配置与稳定首领目录

**Files:** 新建world_boss_materials.py、world_boss_material_plan.py、TestWorldBossMaterialPlan.py；修改config_integrity.py、account_repository.py、account_field_metadata.py、DailyTask.py默认配置。

**Interfaces:** 输出WORLD_BOSS_TARGETS、MATERIAL_TARGETS、material_plan、choose_material_target、material_plan_revision，供UI和执行入口使用。

- [ ] 从现有4C导航、项目证据及可核对的F2讨伐强敌列表整理名称；每项记录稳定ID、别名、场景profile和序号提示，只有名称与突破领奖入口核对过的目标加入支持目录。目录版本不沿用硬编码20来判断当前游戏总项数。
- [ ] 写规则测试，验证默认关闭、固定三行、有限整数、重复目标拦截及累计优先级。

```python
def test_completed_first_target_advances(self):
    keys = [target.key for target in WORLD_BOSS_TARGETS[:2]]
    self.assertEqual(2, len(keys))
    rows = [{'boss': keys[0], 'limit': 3},
            {'boss': keys[1], 'limit': 2}, {'boss': 'none', 'limit': 0}]
    self.assertEqual((keys[1], 2), choose_material_target(rows, {keys[0]: 3}))
    self.assertIsNone(choose_material_target(rows, {keys[0]: 3, keys[1]: 2}))
```

- [ ] 运行新增测试，确认缺少模块/函数时失败，再实现按序遍历与次数欠额；0/none跳过，全部达标返回None，不选择列表首项。

```python
def choose_material_target(rows, counts):
    for row in rows:
        if row['boss'] == 'none' or row['limit'] == 0:
            continue
        missing = row['limit'] - counts.get(row['boss'], 0)
        if missing > 0:
            return row['boss'], missing
    return None
```

- [ ] 在PROTECTED_TASK_KEYS、_TASK_KEY_TYPES、_BOOTSTRAP_TASK_DEFAULTS添加新list字段；normalize校验调用material_plan，缺少新字段作为增量默认允许。AccountRepository的账号/模板读取补[]，保存经过原完整性事务。
- [ ] 测试旧账号缺字段有效、显示关闭，明确已有三目标不被默认覆盖；模板设置不携带运行进度。
- [ ] 用本地解释器运行 `-m unittest tests.TestWorldBossMaterialPlan tests.TestConfigIntegrity tests.TestAccountFieldMetadata tests.TestAccountConfigEditor`，记录通过结果并审阅本任务diff。

## Task 2：跨日累计与领奖事件

**Files:** 创建world_boss_material_progress.py；扩展TestWorldBossMaterialPlan.py；修改account_config_bundle.py及TestAccountConfigBundle.py。

**Interfaces:** 使用现有service.get_progress/update_progress；输出WorldBossMaterialProgress和preserve_material_progress。

- [ ] 写账号隔离、pending拦截、resolve幂等与重启持久化测试；测试结构沿用TestWeeklyBossPlan的临时账号完整性服务夹具。

```python
def test_resolve_is_idempotent(self):
    progress = WorldBossMaterialProgress(self.service, self.profile_id)
    boss = WORLD_BOSS_TARGETS[0].key
    event = progress.begin(boss, 60, 'revision-1')
    progress.resolve(event, True)
    progress.resolve(event, True)
    self.assertEqual(1, progress.counts()[boss])
    self.assertEqual({}, progress.pending())
```

- [ ] 实现独立ledger键；begin原子检查无pending再写事件，resolve仅pending→confirmed加1，cancelled不增加；invalid记录抛错，不能当空记录消费。
- [ ] 写确认存储失败、跨04:00/跨周、更名/换序列/换排序、降低上限、再选同一首领的测试；累计键始终profile_id+boss_id。
- [ ] 实现显式校正和事件核对记录；有pending时先核对后校正。
- [ ] 在账号包恢复中继preserve_weekly_progress之后调用preserve_material_progress；合并较高计数与事件终态，测试备份导入不能丢失未核验事件。现有导出若已包含完整progress则直接复用，测试证明即可。
- [ ] 运行 `-m unittest tests.TestWorldBossMaterialPlan tests.TestWeeklyBossPlan tests.TestAccountConfigBundle`，审阅两类进度没有共享计数或周一清零。

## Task 3：复用4C单轮与材料领奖

**Files:** 修改FarmEchoTask.py；创建WorldBossMaterialTask.py；创建TestWorldBossMaterialTask.py；扩展TestFarmEcho.py；config.py注册隐藏任务。

**Interfaces:** 输入目录、计划、WorldBossMaterialProgress和DailyReservePolicy；输出farm_cycle和MaterialRunResult。

- [ ] 先给原4C流程补共享单轮回归：未入战、入战、复活、各声骸拾取方式、特殊场景再挑战、用户停止传播；原有do_run通过farm_cycle继续运行。
- [ ] 将现有一轮接近/交互、combat_once及拾取步骤移入farm_cycle，返回结果；材料模式pickup_echo=False，让领奖先于可选声骸拾取，不用声骸掉落证明成功。
- [ ] 新任务继承FarmEchoTask，沿用teleport_to_configured_boss_and_prepare、场景profile、复活和移动。选择Boss Challenge，传送前与进入后核对名称；ordinal提示变化时走按名称定位，不把旧序号映射成新首领。
- [ ] 材料实例接管handle_claim_button及on_combat_check中的F交互；巡检scroll_and_click_buttons、宝箱/场景方法和异常恢复，所有消费由统一领奖阶段授权。原实例默认行为继续ESC取消。
- [ ] 写两个相同领奖画面分支测试：普通4C取消且账本不变，材料实例只有目标与状态匹配才确认。
- [ ] 实现每次单倍领取：核验目标、费用、资源、账号和新计划，写pending后才发可能消费的输入；识别结算后resolve(True)立即落盘，后续错误不撤销已计数。

```python
# 在目标/费用/资源均已核验后执行；不把下面顺序放进战斗巡检回调。
guard()
event_id = progress.begin(boss_id, observed_cost, material_plan_revision(rows))
self.send_key('f')
self._confirm_material_reward_once(observed_cost)
self._wait_material_settlement()
progress.resolve(event_id, True)
```

上述两个私有方法由本任务定义：`_confirm_material_reward_once(cost: int) -> None`唯一确认已核验的单倍按钮；`_wait_material_settlement() -> None`仅在对应结算可见时返回，否则抛结果未知异常。不同对话框布局分别验证，不直接假设左右按钮。

- [ ] 写begin写入失败不按F、结果未知保留pending、重复回调只计1次、确认写入失败不再挑战、成功后关闭界面失败仍计数、死亡/声骸吸收不计数、只差1次不能双倍的测试。
- [ ] 异常释放本任务输入并保存okww监控室证据；用户停止信号立即传播，不能被4C的普通恢复分支吞掉。材料失败不调用后台自动战斗禁用。
- [ ] 运行 `-m unittest tests.TestFarmEcho tests.TestWorldBossMaterialTask tests.TestWeeklyBossTask tests.TestDailyReservePolicy tests.TestStaminaAccounting`，审阅原刷4C/周本保持各自领奖行为。

## Task 4：每日体力统一调度与联动

**Files:** 修改DailyTask.py及TestDailyActivityFlow.py；扩展TestWorldBossMaterialTask.py、TestMultiAccountDailyTask.py、TestDailyReservePolicy.py。MultiAccountDailyTask.py仅在展示新增阶段确有需要时修改。

**Interfaces:** 输入run_for_profile和原Which to Farm/Material Planner Enabled；输出_run_profile_stamina供正常清体力和局部补跑共同调用。

- [ ] 写有首领欠数优先材料、目标完成继续下一个、全部达标分别进入Tacet/Forgery/Simulation、养成规划开启继续原分支的测试。
- [ ] 实现run_for_profile每次领奖后读取新计划，达到上限后再挑战前退出；未启用返回plan_disabled，全达标返回complete，已知体力不足返回resource_shortfall，结果未知抛错。read_tasks由已验证profile_id调用AccountRepository.load_profile(profile_id).tasks取得，不能依赖当前下拉框名称或另一个账号的活动状态。
- [ ] 将原清体力分支搬入统一入口，流程为材料调度→资源与活跃度复读→原养成规划或体力任务。resource_shortfall不越过未完成目标直接消费另一个副本；已完成目标允许当次交接后续用途。
- [ ] 两个DailyTask调用点都使用统一入口，传现有账号绑定与资源策略。后续任务继续用最新实际已用体力，不能用调用前旧值再次授权备用体力。
- [ ] 写180活跃度预算先花60再交接、满活跃度仍清当前体力、读数未知不授权备用、材料领取/转换结果未知不再消费、局部补跑不重领已确认事件的测试。
- [ ] 单/多账号用同UUID先后运行测试共享累计，多账号换UUID清理材料实例临时状态；沿用原账号切换与失败收尾。
- [ ] 运行 `-m unittest tests.TestWorldBossMaterialTask tests.TestDailyActivityFlow tests.TestDailyReservePolicy tests.TestStaminaAccounting tests.TestMultiAccountDailyTask`。

## Task 5：账号界面、完成检查和证据

**Files:** 创建WorldBossMaterialPlanWidget.py和TestWorldBossMaterialUI.py；修改AccountConfigTab.py、account_field_metadata.py、CompletionCheckTab.py；扩展TestCompletionCheckUI.py、TestAccountConfigEditor.py。

**Interfaces:** 控件 `WorldBossMaterialPlanWidget(tasks, service=None, profile_id=None, parent=None)`，`values() -> list[dict]`、`refresh() -> None`、`changed`信号；使用progress进行显式核对和校正。

- [ ] 测试三行首领/次数/进度控件、0跳过、无默认关闭、非法数字拦截、保存round-trip、模板不带进度。
- [ ] 实现周本式行布局；本账号体力模块及新账号模板都挂载，保存通过editor.save_draft，摘要显示“剩余n次 / 已达标，后续：账号体力用途”。
- [ ] 累计校正和pending核对需任务停下，明确提示首领与事件；分别调用correct、resolve，刷新当前账号界面，不修改其他账号。
- [ ] 完成检查读取同一ledger显示材料进度及待核验，不按凌晨时间清零，不因未来累计需求未达标直接使本日活跃度完成失败。
- [ ] 结算与错误证据调用现有存储服务；测试实际目标路径在okww监控室内，运行日志脱敏。新需求不扫描或导出材料产出数量。
- [ ] 运行 `-m unittest tests.TestWorldBossMaterialUI tests.TestAccountFieldMetadata tests.TestAccountConfigEditor tests.TestCompletionCheckUI tests.TestCompletionEvidence`，检查UI渲染和账号切换后刷新。

## Task 6：完整验收、文档与发布

**Files:** 修改config.py、README.md、更新日志.md；创建docs/references/world-boss-materials.md；更新本文实施勾选和验证结果。

- [ ] 完整离线组合：前三个WorldBossMaterial测试、TestFarmEcho、TestDailyActivityFlow、TestDailyReservePolicy、TestStaminaAccounting、TestWeeklyBossPlan、TestWeeklyBossTask、TestAccountConfigBundle、TestConfigIntegrity、TestMultiAccountDailyTask、TestCompletionCheckUI、项目现有自动战斗持久性/输入所有权测试。
- [ ] 用真实界面核对首领目录与领奖布局：大世界目标及独立场景目标分别验证单次/重复/最后一次领奖；单账号与多账号验证共享计数。补齐目标/事件/资源证据记录；无实机证据的流程明确报告验证边界。
- [ ] 实机验收矩阵：目标1差1次、目标2还差2次、体力足够，确认同次切换；全部达标分别转凝素和无音区；体力不足保留进度；停止/重启无重复计数；普通4C不花材料体力。
- [ ] 修正具体失败并只重复相关风险测试，确认原自动战斗偏好和账号切换链路未变。
- [ ] 按实施时基线升中等版本（当前拟1.93.00），同步发布说明和使用手册，记录目标上限是历史累计数，首次老账号默认关闭。
- [ ] 审阅git diff，stage只含本功能文件；构建源码更新包并对上一发布标签做verify_update_package校验，确认configs/监控证据不在包内。
- [ ] 一次功能发布提交，创建匹配固定宽度注释标签，推送GitHub；发布至唯一当前NAS。读回latest.json与远端包SHA-256，经生产下载链路复验。
- [ ] 最终报告包含实现版本、验证项、实机限制、GitHub/NAS发布结果；本文状态改“已实施”，不能仅因写完代码就填写全流程实机通过。

## 计划自检

- 计数不依赖掉落数量：Tasks 2/3；普通4C领奖隔离：Task 3。
- 跨日、跨账号、备份恢复：Task 2；旧配置/模板：Tasks 1/5。
- 多目标同次切换、后续跟随账号选择、现有养成规划、局部补跑：Task 4。
- 原自动战斗持续启用和单输入所有者：Tasks 3/4/6。
- 证据汇聚、UI可核对、版本及NAS发布：Tasks 5/6。
- 当前仅文档，未调用真实任务、未修改程序配置或版本号。
