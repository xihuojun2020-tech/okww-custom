# Daily Priority Scheduling Implementation Plan

**Goal:** 让已核验账号按“周本 → 所选聚落 → 首领材料 → 有限凝素 → 无音区”的顺序运行，只在开头、结尾及备用体力转换前查看活跃度，以游戏实际分数判定是否完成。

**Architecture:** 保留 `DailyTask` 为编排入口，复用现有聚落、周本、首领、领域、无音区战斗代码。新增小型凝素限额计划与原子领奖日志；账号配置只新增可选字段，旧选择和历史记录原样保留。

**Tech Stack:** Python 3.12、ok-script、PySide6、`ConfigIntegrityService` 账号运行状态、`unittest`。

**Spec:** `docs/superpowers/specs/2026-10-05-daily-priority-scheduling-design.md`

## Global Constraints

- 代码修改必须在同一发布中更新 `config.py` 的固定宽度版本号；当前基线 `1.97.08`，若无并行版本，目标 `1.97.09`。验证后仅提交本任务文件，创建对应注释标签并推送分支和标签，除非用户另有指示。
- 在 Windows 用 `\.venv\Scripts\python.exe` 运行测试；若本地 `.venv` 不存在才用全局 Python。
- 所有账号配置和领奖进度以稳定 `profile_id` 为键；每次消费前沿用账号身份与配置完整性校验。
- 未经实际领奖和体力扣除确认，不增加任何有限目标进度；不把本地聚落检查点当成当天活跃度读数。
- 现有工作区含用户原有文档改动。实施时不清理、不覆盖、不将这些改动加入本任务提交。
- 本计划只涉及每日任务；深塔周期状态与关卡策略另有方案，不在本次代码范围。

## 当前流程核查与改动理由

| 位置 | 当前行为 | 与目标的差距 |
| --- | --- | --- |
| `src/task/DailyTask.py:_run_daily_inner` | 开始 `open_daily()`，周本后再打开，聚落后再打开，体力结束再打开；不足时还能调用 `_complete_missing_daily_echo/stamina` | 造成重复翻页，并在最终不足时调用额外模块 |
| `src/task/DailyTask.py:open_daily` | 每次先遍历领取小任务积分，再单独滚动找 180 体力任务，最后 OCR 总分 | 保留积分领取，但只在开头、结尾和备用转换前调用；最终避免再次整页打开 |
| `src/task/DailyTask.py:_daily_objective` | 被 `open_daily()` 调用时仍再次 `_open_daily_page()`，随后上翻和最多六次下翻 | 增加“页面已打开”读法，开头访问中不重复导航；一次遍历同时取得进度 |
| `src/task/weekly_boss.py:weekly_check_window/check_due` | 周二至周六沿用周一窗口并补检 | 自动调用须只发生在周一和周日 |
| `src/task/NightmareNestTask.py:run` | 已能核对并打完选中的具体聚落；`run_capture_mode` 获取一个声骸就停 | 每日应走 `run()`，不再用“获得一个声骸”代替全部目标完成 |
| `src/task/DailyTask.py:_run_profile_stamina` | 首领材料结束后，`Which to Farm` 单选一种体力用途；材料规划开关会转到背包 OCR 规划 | 需要把有限凝素两个目标及无音区接成顺序，并停止调用旧扫描器 |
| `src/task/world_boss_material_plan.py` + `WorldBossMaterialTask` | 达到累计上限即停止，账号界面仍显示启用；再次开启需自己算累计值 | 达标后自动关闭本组；下一轮提供“新增 N 次”入口 |
| `src/task/DomainTask.py`、`TacetTask.py` | `must_use` 同时承担每日备用体力预算和普通刷取停止阈值 | 分开“为了活跃度允许转换多少备用”和“现有体力继续刷到何时” |

## 文件职责与接口

- 新建 `src/task/forgery_quota_plan.py`：解析至多两个有序目标、计算绿色当量、选择 40/80 体力。接口：`forgery_plan(tasks) -> list[dict]`、`green_units(counts) -> int`、`next_forgery_claim(rows, earned, current_stamina) -> tuple[int, int] | None`，返回 `(domain_serial, max_claims)`。
- 新建 `src/task/forgery_quota_progress.py`：按 `profile_id + goal_id` 记录 pending/confirmed/cancelled 领奖、累计等价量；提供 `begin`、`resolve`、`pending`、`earned`、`preserve_forgery_progress`。
- 修改 `src/task/ForgeryTask.py` 和 `src/task/DomainTask.py`：从已选凝素目标驱动现有战斗与领奖，使用通用 `claim_tracker` 钩子记录一次 40 或 80 体力领取；旧 `material_planner` 钩子在过渡期兼容。
- 修改 `src/task/DailyTask.py`：把分支改成明确的五阶段编排；开头及结尾的活跃度页面访问各一次，备用转换为唯一中途例外；删除最终自动补刷其他模块的调用。
- 修改 `src/task/weekly_boss.py`、`src/task/MultiAccountDailyTask.py`：周二至周六均不产生周本自动待办，保持周一和周日独立记录。
- 修改 `src/task/world_boss_material_plan.py`、`src/gui/WorldBossMaterialPlanWidget.py`：已达标组自动取消启用；下次设置 N 次时自动换算为后端累计上限。需要账号编辑事务时复用 `AccountRepository.publish_profile` 的版本比较。
- 新建 `src/gui/ForgeryQuotaWidget.py`，修改 `src/gui/AccountConfigTab.py`、`src/account_field_metadata.py`、`src/config_integrity.py`、`src/account_repository.py`：每账号两个凝素目标，每个目标选领域与四个品质数量；保存时验证，旧账号缺新字段合法。
- 修改 `src/account_config_bundle.py`、`src/config_backup.py`：导入/恢复不得丢失或倒退凝素待核验事件与已确认进度。
- 修改相应 `tests/Test*.py`、任务说明与发布记录。保留 `MaterialPlannerTask.py` 作为历史代码，但从每日入口断开调用；不做无关重构。

## Task 1：兼容配置与纯计算

**Files:** 新建 `src/task/forgery_quota_plan.py`；修改 `src/config_integrity.py`、`src/account_repository.py`、`src/task/DailyTask.py` 的默认值/保护键；新建 `tests/TestForgeryQuotaPlan.py`。

**Interfaces:** 配置键 `Forgery Material Goals` 是可缺省列表，最多两行；每行 `{goal_id: str, domain: int, need: {gold: int, purple: int, blue: int, green: int}}`。`goal_id` 为目标轮次的稳定 UUID，编辑本轮数量保留 ID，明确新建一轮才换 ID。旧配置没有此键等价于 `[]`，不写回或改动旧值。

- [ ] 写失败测试：`27*金+9*紫+3*蓝+绿`；数量非负整数；领域序号必须为现有 `FORGERY_DOMAIN_OPTIONS`；至多两行；40/80 的边界包括剩余 1、25、26、49、50 当量和体力 39、40、79、80。
- [ ] 写最小计算函数，例如：

  ```python
  def green_units(need):
      return 27 * need['gold'] + 9 * need['purple'] + 3 * need['blue'] + need['green']

  def claim_width(remaining_units, current_stamina):
      if remaining_units >= 50 and current_stamina >= 80:
          return 2  # 一次 80 体力，按 50 当量
      if remaining_units > 0 and current_stamina >= 40:
          return 1  # 一次 40 体力，按 25 当量
      return 0
  ```

- [ ] 将新键列入 `PROTECTED_TASK_KEYS`、类型校验和旧版缺省许可；账号读取和模板保留旧字段。给 `Which to Farm` 添加明确“无”选项，但不把旧账号的已有值迁移为“无”；保留旧版模拟领域入口。
- [ ] 验证：`.\.venv\Scripts\python.exe -m unittest tests.TestForgeryQuotaPlan tests.TestAccountConfigEditor`。

## Task 2：周本只在周一与周日自动执行

**Files:** 修改 `src/task/weekly_boss.py`、`src/account_field_metadata.py`、`tests/TestWeeklyDailyIntegration.py`；检查 `src/task/MultiAccountDailyTask.py:_is_done` 的调用结果。

**Interfaces:** `weekly_check_due(target, completed, now)` 保持原签名；在北京时间 04:00 切换后的游戏日期仅星期一、星期日可能返回 `True`。`WEEKLY_MONDAY` 和 `WEEKLY_SUNDAY` 的独立完成记录保留。

- [ ] 将现有“周二到周六补检”测试改为那五天均 `False`；补测周一未做而周日应继续、周一做完周日仍复核、周日做完下周一重置、03:59/04:00 边界。
- [ ] 在 `weekly_check_due` 的目标合法性校验之后、读取完成时间之前加入游戏星期门禁；`DailyTask.check_weekly_boss` 和多账号 `_is_done` 共用它，不各写一套日期判断。
- [ ] 周本可用三次的游戏读数与领奖安全逻辑不动；周日若余数为 0，只记录复核完成，不开战。
- [ ] 验证：`.\.venv\Scripts\python.exe -m unittest tests.TestWeeklyDailyIntegration`。

## Task 3：聚落按已选列表完成

**Files:** 修改 `src/task/DailyTask.py`、`src/account_field_metadata.py`、`src/gui/AccountConfigTab.py` 的旧开关展示；修改 `tests/TestNightmareNestTask.py`、`tests/TestDailyRegressionFlow.py`。

**Interfaces:** `selected_nests = (Tacet Discord Nests to Farm, Nightmare Settlements to Farm)`；两表都空则不调用 `NightmareNestTask`。非空则配置目标并调用 `NightmareNestTask.run()`，其 `_assert_selected_targets_complete()` 为模块完成判据。

- [ ] 写测试：旧列表原样保留；总开关关闭但列表非空仍执行；总开关开启但列表全空跳过；游戏页已满进度则跳过战斗；一个目标未完成不能写当天聚落完成检查点。
- [ ] 移除每日主流程对 `run_capture_mode`、`_complete_missing_daily_echo` 的自动调用。保留旧键但隐藏/标注停用，防止旧账号勾选数据被清空。
- [ ] 只在全部已选目标得到游戏进度确认后写按账号、按目标列表摘要的当天检查点。失败后保留安全返回和错误记录，后续已选体力阶段可继续，最终状态不能声称聚落已完成。
- [ ] 验证：`.\.venv\Scripts\python.exe -m unittest tests.TestNightmareNestTask tests.TestDailyRegressionFlow`。

## Task 4：首领材料达标后关闭，下一轮易于开启

**Files:** 修改 `src/task/DailyTask.py`、`src/gui/WorldBossMaterialPlanWidget.py`；必要时增加 `src/task/world_boss_material_plan.py` 的小函数；修改 `tests/TestWorldBossMaterialPlan.py`、`tests/TestWorldBossMaterialUI.py`。

**Interfaces:** 现有 `WorldBossMaterialProgress` 的成功领奖计数和 pending 事件不变。关闭规则：三行已启用目标均满足后，在安全边界通过账号配置的版本比较发布，把这些行 `limit` 置 0，保留 `boss` 和历史计数；并发编辑时不覆盖新配置，保留“已达标、待关闭”状态重试。

- [ ] 写测试：仅一次成功领奖更新进度；全部目标达标后自动禁用；部分达标仍转下一行；pending 事件、配置修订冲突或保存失败不把领奖重复计入；旧账号原有行不重置。
- [ ] 在账号界面给已关闭行增加“本轮新增 N 次”操作，读取该首领当前累计值并保存为 `累计值+N`；不要求用户自己相加。保留旧行中已录入的绝对累计上限。
- [ ] `DailyTask` 在材料任务完成返回后尝试自动关闭；关闭失败发出清晰日志，下一次运行仍由现有计数挡住重复刷取。
- [ ] 验证：`.\.venv\Scripts\python.exe -m unittest tests.TestWorldBossMaterialPlan tests.TestWorldBossMaterialUI`。

## Task 5：凝素有限目标的原子进度

**Files:** 新建 `src/task/forgery_quota_progress.py` 和 `tests/TestForgeryQuotaProgress.py`；修改 `src/account_config_bundle.py`、`src/config_backup.py`。

**Interfaces:** 运行状态键包含稳定 `profile_id`。每个 `goal_id` 存已确认绿色当量和事件；事件含领域、目标修订、期望消费 40/80、pending/confirmed/cancelled、时间。`begin` 先落盘再点击领奖，`resolve` 幂等；pending 阻止再次消费，提供人工“已领取/未领取”核对入口。80 体力确认后加 50，40 加 25，其他消费量视为异常待核验。

- [ ] 写测试：同账号跨天续跑、两个账号隔离、两组目标顺序、重复 resolve 不重复加数、写盘失败保留 pending、异常消耗不进账、导入/备份恢复不得减小计数或丢失 pending。
- [ ] 用 `ConfigIntegrityService.update_progress` 实现原子事件，不读背包、掉落 OCR 或培养目标。编辑同一 `goal_id` 的目标数量继续用本轮累计；新建一轮生成新 ID，不复用历史已完成量。
- [ ] 在配置导入与备份恢复处调用 `preserve_forgery_progress`，行为与现有首领材料日志一致。
- [ ] 验证：`.\.venv\Scripts\python.exe -m unittest tests.TestForgeryQuotaProgress tests.TestAccountConfigBundle`。

## Task 6：复用领域领奖实现有限凝素与无音区接力

**Files:** 修改 `src/task/DomainTask.py`、`src/task/ForgeryTask.py`、`src/task/TacetTask.py`、`src/task/DailyTask.py`；新增 `tests/TestForgeryQuotaIntegration.py`，同步 `tests/TestMaterialIntegration.py`。

**Interfaces:** `DomainTask` 把现有 `material_planner` 领奖钩子泛化为 `claim_tracker`，兼容旧属性。`ForgeryTask.farm_quota(profile_id, read_tasks, service, guard, activity_ready, used_stamina)` 按目标和剩余体力选择 `max_claims`，每次领取后重读进度与配置；目标 1 满足才到目标 2，全部完成返回 `complete`，再由 `DailyTask` 调 `TacetTask.farm_tacet`。

- [ ] 写测试：剩余 49 当量强制单倍；剩余 50 且当前 80 才可双倍；体力 40～79 只领单倍；领奖 0 次不进账；中断后 pending 阻止重复；目标 1 完成转目标 2；全部完成进入该账号配置的无音区。
- [ ] `DomainTask` 在消费前调用 `begin_claim()`，经现有 `_confirm_stamina_used()` 验证后 `collect_claim(used)`；异常走 `capture_failure()`，不继续挑战。旧 `MaterialPlannerTask` 可以保留类和兼容测试，但每日入口不调用。
- [ ] 解耦“正常当前体力继续刷”和“为了补活跃度可转换的备用体力预算”：凝素直到目标完成或当前体力不足 40；无音区直到当前体力不足 60；预算归零后不能再转换备用，但当前体力仍可继续消费。用现有 `DailyReservePolicy` 阻止活跃度满、未知或读数过期时转换。
- [ ] 新目标列表为空且旧 `Which to Farm = Forgery Challenge` 时仍调用旧 `farm_forgery`；原 `Material Planner Enabled` 不再改变该选择。`Which to Farm = Simulation Challenge` 仍运行原模拟领域。`Which to Farm = 无` 时不运行这组体力任务。
- [ ] 验证：`.\.venv\Scripts\python.exe -m unittest tests.TestForgeryQuotaIntegration tests.TestMaterialIntegration tests.TestDailyReservePolicy`。

## Task 7：每日活跃度首尾两次访问与转换前例外

**Files:** 修改 `src/task/DailyTask.py`、必要时修改 `src/task/BaseWWTask.py` 的预算参数；修改 `tests/TestDailyActivityFlow.py`、`tests/TestDailyRegressionFlow.py`、`tests/TestWeeklyDailyIntegration.py`、`tests/TestDailyReservePolicy.py`。

**Interfaces:** 主路径顺序为：账号绑定/验证 → 一次 `open_daily()`（领取已完成小任务积分并读取分数/180 体力进度）→ 到期周本 → 所选聚落 → 所选首领材料 → 本账号体力路线 → 一次收尾领奖与分数核验 → 邮件/战令/既有周常收尾。普通阶段之间不调用 `open_daily()`。`_refresh_reserve_activity()` 仅在准备转换备用体力时调用，且每次转换前刷新读数。

- [ ] 写事件序列测试：正常执行只有开头与结尾两次活跃度页访问；转换备用体力前允许额外一次；周本/聚落/首领/凝素/无音区按序；空聚落列表跳过；已有 100 分直接完成；结束不足 100 不调用 `_complete_missing_daily_echo/stamina` 或任何未选模块。
- [ ] 把 `open_daily()` 从周本后、聚落后、首领后等常规调度节点移除。保留小任务积分领取；最终 `claim_daily()` 在同一页面完成积分、宝箱和总分复核，避免关闭页面后再 `open_daily()` 整页扫描。
- [ ] 让 `_daily_objective('stamina')` 可在当前已打开的任务页读取，不从 `open_daily()` 内再次 `_open_daily_page()`；将最后的 `claim_daily()` 调整为返回同页复核的分数/状态，`_finish_daily_rewards()` 不再为确认结果重新打开整页。
- [ ] 对备用体力转换建立“准备消费 → 返回世界 → 新读数 → 本次转换 → 核验余额”的单次循环；若活跃度已满、读数未知、账号变更、转换金额未核实，则停止备用转换，但不妨碍继续使用已确认的当前体力。
- [ ] 删除最终自动补做聚落和 180 体力任务的调用。收尾实际分数 <100 时仍可领取已达成档位，然后抛 `DailyActivityIncomplete`，该账号不写 `Daily Task` 完成记录；分数未知抛 `DailyActivityDetectionError`。
- [ ] 验证：`.\.venv\Scripts\python.exe -m unittest tests.TestDailyActivityFlow tests.TestDailyRegressionFlow tests.TestWeeklyDailyIntegration tests.TestDailyReservePolicy tests.TestMultiAccountDailyTask`。

## Task 8：账号界面、回归与发布

**Files:** 新建 `src/gui/ForgeryQuotaWidget.py`；修改 `src/gui/AccountConfigTab.py`、`src/account_field_metadata.py`、`tests/TestAccountConfigEditor.py`、`tests/TestMaterialIntegration.py`、`config.py`、`docs/references/activity-tasks.md` 和相关本地化资源。

**Interfaces:** 每账号界面显示最多两个凝素目标：领域、金/紫/蓝/绿“本轮还需”、折算总当量、已确认当量、预计 80/40 领取次数、pending 核对。空目标不触发有限模式；旧体力用途选择保持原值。账号模板可复制目标意图但不可复制 `goal_id` 进度，新账号须生成新目标轮次 ID。

- [ ] 写账号配置往返测试：旧账号全部原有勾选和 `Which to Farm` 字节级保留；新字段缺省合法；保存目标、切账号、导出导入后仍是本账号目标；编辑目标时不复制别人的进度；“无”选项可保存。
- [ ] 更新 UI 元数据、总开关停用提示、周本检查日说明、材料目标状态。显示“凝素目标已完成，接下来刷无音区”以及首领材料自动关闭结果，避免界面显示仍在运行。
- [ ] 用本地 `.venv` 跑相关单元与集成测试，再跑仓库既有发布验证；目标版本在 `config.py` 与产品版本文案同步。检查主工作区和打包版均包含该版本，打包增量包通过 `scripts/verify_update_package.py` 和 `scripts/package_smoke.py`，进行启动/账号配置/任务入口烟测。
- [ ] 真实游戏验收至少覆盖：一个已满 100 分账号、一个需刷聚落的账号、一个有 40/80 凝素余量的账号、一个仅周日补检账号；人工核对体力扣除与游戏分数。没有这些实机证据时只报告自动测试通过，不宣称整条游戏流程已验证。
- [ ] 按仓库 `AGENTS.md` 在代码验证后提交本任务文件、打 `vX.YY.ZZ` 注释标签并推送，核对远端提交与标签一致；安装器/更新包的实际可用状态单独核验。

## 最终验收清单

- [ ] A1/A3/A4 等账号的旧选择保持原样；新目标和进度互不串号。
- [ ] 周二至周六不会因周一本周未完成而调用周本；周日会复核。
- [ ] 已选聚落全部以游戏进度确认；空列表跳过，不推断活跃度不足。
- [ ] 首领材料达标自动关闭；再次开启输入的是本轮追加次数。
- [ ] 凝素两组按当量和真实 40/80 体力扣除累计；旧凝素配置无目标时继续旧刷法；完成后转该账号无音区。
- [ ] 无备用体力转换时活跃度页仅开头、结尾访问；转换前的复核是唯一中途例外。
- [ ] 最终 100 分以游戏读数为准；不足或未知不标记每日完成，也不临时调用未选模块。
