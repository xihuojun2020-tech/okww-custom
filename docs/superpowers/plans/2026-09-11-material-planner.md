# 鸣潮养成材料规划与收益统计 Implementation Plan

> 执行说明：本次交付只包括设计与计划，不启动编码或游戏操作。后续按以下任务在当前线程逐项执行、验证；未获用户要求不自行创建其他代理或任务。本文所有新增接口都是拟实现接口，不代表当前仓库已存在。

**Goal:** 读取游戏培养目标与实际仓库，按材料缺口复用现有刷本，并永久保存完整结算及以绿色目标格子数确定的奖励份数。

**Architecture:** 材料字典和纯计算独立于UI；三个扫描入口分别生成需求、库存和收益。SQLite与不可变原图持久化，单个协调任务接入既有账号、周本、凝素和声骸任务。

**Tech Stack:** 现有 Python、ok-script OCR/特征/截图、OpenCV、NumPy；标准库 dataclasses、sqlite3、json、unittest；不新增远端服务。

**Spec:** [需求及设计](../specs/2026-09-11-material-planner-design.md)。基线 `c82e10fc`、版本 `1.58.00`，实施前重新确认HEAD和脏文件，不覆盖他人修改。

## Global Constraints

- 只用迅刀、音感仪、长刃、臂铠、佩枪文字与材料图标定位凝素，不依赖副本名称。
- 十组四档，相邻品质3:1向上，不能向下或跨组；通用材料不抵扣，“可补齐”不作完成依据。
- 共鸣者突破材料仅记录，不阻塞声骸；周本从培养页读取，不要求扫描仓库；未指定周本选游戏列表首项。
- 奖励份数是完整去重列表内目标组绿色格子数；不是绿色数量、截图数量或体力/40。
- 不判断活动、不对显示掉落倍乘；保存实际消耗和实际掉落。
- 统计数据和原图永久保留，不自动删除；异常记录保留，不作为零样本。
- 周一全仓库校准，错过补扫；局部库存和需求修订用于临近停刷，不从收益直接覆盖真实库存。
- 首版均值仅统计展示，预测控制另阶段验收。
- Windows Python 首选 `.\.venv\Scripts\python.exe`，存在即不可使用全局Python。
- 后续代码发布遵守AGENTS：固定宽度版本、同步发布说明、验证后提交/注释标签/推送；本次文档不升版。
- 账号切换实现不重写；若触碰生产切换路径，TestAccountSwitchTask须同步复用生产路径。

## 1. 文件职责与依赖

| 新增文件 | 职责 |
|---|---|
| `src/materials/__init__.py` | 包入口，禁止导入即创建数据库或输入游戏 |
| `src/materials/model.py` | 结构、四档合成缺口、周标记、奖励份数和加权统计 |
| `src/materials/catalog.py` | 加载字典、校验组与品质、按名称/模板确定材料 |
| `assets/materials/catalog.json`、`assets/materials/templates/` | 40凝素材料及其他已确认类别的图标/名称元数据 |
| `src/materials/vision.py` | 纯图像解析、格子识别、有序跨屏拼接，不操作游戏 |
| `src/materials/repository.py` | SQLite快照、领取意图、不可变截图、解析修订、查询、备份 |
| `src/task/MaterialPlannerTask.py` | ok-script页面交互、扫描、领取上下文和规划协调 |
| `tests/TestMaterialModel.py`、`TestMaterialCatalog.py`、`TestMaterialVision.py`、`TestMaterialRepository.py`、`TestMaterialPlannerTask.py`、`TestMaterialIntegration.py` | 对应算法、真实截图回放、存储及任务契约 |
| `tests/images/materials/manifest.json`及脱敏图 | 输入、人工标签和源文件摘要 |

修改现有 `BaseWWTask.py`、`DomainTask.py`、`ForgeryTask.py`、`DailyTask.py`、`WeeklyBossTask.py`、`weekly_boss.py`、`config.py`；配置字段沿用 `account_field_metadata.py` 和现有账号编辑器注册方式。优先用现有 info 显示进度；不另造整套页面或重构现有编辑器。

依赖顺序：任务1素材 → 任务2模型/字典 → 任务3持久化与任务4视觉（按顺序执行即可）→ 任务5扫描 → 任务6结算接入 → 任务7刷取调度 → 任务8展示/统计 → 任务9验收发布。每任务落地后先过其测试再进行下一项，不因本文提供规划而自动发布未验证代码。

## 2. 公共数据契约

所有时间用带时区ISO字符串；账号是现有稳定 profile_id；数量未知用 `None` 而非0。

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Counts:
    green: int = 0
    blue: int = 0
    purple: int = 0
    gold: int = 0

@dataclass(frozen=True)
class Gap:
    missing: Counts
    synthesis: Counts  # green恒为0，其他档表示虚拟合成次数

@dataclass(frozen=True)
class Drop:
    position: tuple[int, int]  # 拼接后的绝对行、列
    item_id: str
    group_id: str | None
    rarity: str
    amount: int

@dataclass(frozen=True)
class Settlement:
    claim_id: str
    profile_id: str
    target_revision: str
    target_group: str
    stamina: int | None
    complete: bool
    drops: tuple[Drop, ...]
    reward_units: int | None
    errors: tuple[str, ...]
```

Counts验证非负整数；OCR数据先严格解析再进入Counts。`Gap`和`Drop`不承载图像，原始坐标和帧引用由解析记录保存。本计划伪代码中的`task`均指现有执行器拥有的任务实例，不另起UI线程操作游戏。

## 任务1：固定样本与人工标注

**文件：** 创建 `tests/images/materials/manifest.json`、`tests/images/materials/*.png`、`assets/materials/templates/*.png`；仅复制源截图。

**产出：** 清单中每张图包含 `fixture_id、source_basename、source_sha256、width、height、scene、expected`；expected包含可读格子的box、品质、数量、目标组及跨屏对应关系。

- [ ] 检查设计第8节的15张原图全部存在，保留原图不动，逐张确认尺寸。产出脱敏回放副本，遮住右下账号标识和无关信息。
- [ ] 标注十组四十档模板，组a/b依据实际图标定义，不按副本名字命名。每个模板避开数量、新标记、头像、选中框；无法完整裁切的图标要求新的真实样本，不能用截断模板充当完整模板。
- [ ] 标注培养页材料分界、两组凝素、两组怪物、周本次数；仓库底部；17:40两帧的绝对行对应。
- [ ] 创建最小样本核验测试，先验证结算人工标签为绿13蓝16紫3金0、绿色格子2、等价88；此步不宣称已OCR成功。

```python
def test_reference_annotations(self):
    sample = self.manifest['settlement_1740']
    self.assertEqual(sample['expected']['counts'], [13, 16, 3, 0])
    self.assertEqual(sample['expected']['reward_units'], 2)
    self.assertEqual(sample['expected']['stamina'], 80)  # 来源：用户说明
```

- [ ] 记录单份、四份、零库存、完整20条目入口、右侧详情换选的真实样本缺口；取得这些样本是任务9实机门槛，不阻止先完成离线算法。没有真实样本的场景必须标“未验收”。

## 任务2：字典与单向合成模型

**文件：** `src/materials/model.py`、`catalog.py`、`assets/materials/catalog.json`、`tests/TestMaterialModel.py`、`TestMaterialCatalog.py`。

**接口：** `equivalent(counts: Counts) -> int`；`calculate_gap(stock: Counts, need: Counts) -> Gap`；`is_satisfied(gap: Gap) -> bool`；`week_id(now: datetime) -> str`；`Catalog(path)` 提供 `find_name(text) -> dict | None`、`get(item_id) -> dict`。条目字段为 `item_id、group_id、weapon_type、rarity、source_type、names、template_paths`。source_type限制为 `forgery、weekly、ascension、monster、gathering、universal、other`。

- [ ] 先写以下算法测试，再运行并确认失败原因是新接口未实现。

```python
def test_gold_cannot_fill_green(self):
    gap = calculate_gap(Counts(gold=1), Counts(green=3))
    self.assertEqual(gap.missing, Counts(green=3))

def test_reserve_lower_tiers(self):
    gap = calculate_gap(Counts(15, 6, 0, 0), Counts(6, 3, 2, 0))
    self.assertEqual(gap.missing, Counts())
    self.assertEqual(gap.synthesis, Counts(0, 3, 2, 0))

def test_negative_rejected(self):
    with self.assertRaises(ValueError):
        Counts(green=-1)
```

- [ ] 按以下逻辑实现，数据验证放Counts构造阶段，不把输入对象改写。

```python
def calculate_gap(stock, need):
    carry = 0
    missing, synthesized = [], []
    for available, required in zip(
            (stock.green, stock.blue, stock.purple, stock.gold),
            (need.green, need.blue, need.purple, need.gold)):
        synthesized.append(carry)
        balance = available + carry - required
        missing.append(max(-balance, 0))
        carry = max(balance, 0) // 3
    return Gap(Counts(*missing), Counts(*synthesized))
```

- [ ] 添加全零、恰好3个、余数1/2、四档链路、低级不足高级富余、跨组独立测试；字典检查同组同品质唯一、每凝素组四档、无通用材料加入forgery组。
- [ ] week_id只取UTC+8减4小时后的周一日期，不直接复用返回周日补检窗口的 `weekly_check_window()` 全返回值；验证周日→周一03:59不跨周、04:00跨周。
- [ ] 运行 `.\.venv\Scripts\python.exe -m unittest discover -s tests -p TestMaterialModel.py`，以及相同形式的 `TestMaterialCatalog.py`；完成后提交本任务文件。

## 任务3：永久持久化与幂等

**文件：** `src/materials/repository.py`、`tests/TestMaterialRepository.py`。

**接口：** `MaterialRepository(root)`；`begin_claim(profile_id, target_revision, group_id, captured_at) -> str`；`save_frame(record_id, frame_seq, png_bytes) -> dict`；`append_settlement(result: Settlement, parser_version: str) -> int`；`save_snapshot(profile_id, kind, payload, captured_at, complete) -> str`；`latest_complete_snapshot(profile_id, kind) -> dict | None`；`pending_claims(profile_id) -> list[dict]`；`backup(destination) -> str`。kind为 `inventory` 或 `target`。

- [ ] 使用临时目录编写首次领取、同claim重复提交、不同claim相同图片、错误解析追加修订、账号隔离、部分快照不替换完整快照测试。所有测试产生的记录不写生产数据根。
- [ ] 建表：`claims`（claim_id主键和固定身份）；`frames`（record_id, frame_seq联合唯一）；`snapshots`；`parses`（claim_id, revision联合唯一）；`drops`（claim_id, revision, row, col联合唯一）。解析输入摘要与parser_version相同则返回已有revision，输入变更才新建修订。
- [ ] PNG使用新文件写入、flush/fsync、原子替换；提交索引前检查原图写入成功。数据库transaction负责一整次解析及drops提交。崩溃留下的原图保留并可复核，不以“孤儿清理”自动删除。

```python
def test_resubmission_is_idempotent(self):
    first = self.repo.append_settlement(self.sample, '1')
    second = self.repo.append_settlement(self.sample, '1')
    self.assertEqual(first, second)

def test_partial_snapshot_not_authoritative(self):
    self.repo.save_snapshot(self.profile, 'inventory', {'a': 8}, self.t0, True)
    self.repo.save_snapshot(self.profile, 'inventory', {'a': 0}, self.t1, False)
    self.assertEqual(self.repo.latest_complete_snapshot(self.profile, 'inventory')['payload'], {'a': 8})
```

- [ ] 对路径越界、图片写入异常、数据库锁超时作失败注入：必须显式失败，不删除历史、不返回“保存成功”。复制现有证据仓库经过验证的机制；不直接依赖其单证据删除流程或吞错误的自动保存包装。
- [ ] 实现SQLite backup和图片复制的手动备份，无轮换。验证运行目录更新、账号配置删除均不影响数据根。
- [ ] 运行 `TestMaterialRepository.py` 后提交。不要新增定时清理入口。

## 任务4：三个页面的纯视觉解析与跨屏拼接

**文件：** `src/materials/vision.py`、`tests/TestMaterialVision.py`，补充任务1标注。

**接口：** `parse_inventory_frame(frame, ocr, catalog) -> dict`；`parse_target_frame(frame, ocr, catalog) -> dict`；`parse_reward_frame(frame, ocr, catalog) -> dict`；`stitch_reward_pages(pages: list[dict]) -> dict`。输入ocr是由任务注入的现有OCR调用适配，测试可注入人工OCR结果；必须另设真实OCR回放测试。

各帧返回 `scene、cells、anchors、partial_cells、errors`；cell含 `local_row、column、box、item_id、group_id、rarity、amount、match_status`。target增加 `boundary_y、target_identity、weekly_remaining、needs`。拼接返回 `complete、drops、frame_links、errors`；Drop.position是绝对行列，不是图片坐标。

- [ ] 先用实际17:40图片编写失败测试：期望重建22个独立奖励格子，3行（8、8、6），目标绿色2格，目标总量13/16/3/0。其他怪物格子不能增加奖励份数。
- [ ] 模板候选只在格子图标区域匹配；逐模板以真实样本确定阈值和第一/第二候选差距，不凭未经标定的固定0.7宣称准确。保存相似度便于复核；不确定返回unknown。
- [ ] 数字只读格子底部，严格匹配 `×N/xN/N`；仓库数量与培养页 `a/b` 单独解析，遮挡或多个冲突结果返回未知。零值与未知分开。
- [ ] 先按行、列及图标序列对齐相邻帧，再结合垂直位移确认绝对行号。重复模式多解返回 `ambiguous_overlap`；等待交互层小幅补滚动。

```python
def test_same_drop_at_different_positions_survives(self):
    drops = [Drop((0, 0), 'g', 'rectifier_a', 'green', 6),
             Drop((2, 1), 'g', 'rectifier_a', 'green', 6)]
    self.assertEqual(len(drops), 2)  # 后续reward_units必须为2，不按名字去重

def test_real_reward_stitch(self):
    result = stitch_reward_pages(self.parsed_reference_pages)
    self.assertTrue(result['complete'])
    self.assertEqual(len(result['drops']), 22)
    self.assertEqual(sum(d.rarity == 'green' and d.group_id == self.target
                         for d in result['drops']), 2)
```

- [ ] 仓库跨屏同item_id只记录一次；数量冲突要求重新读取而非求和/取最大。培养页用材料组及具体图标识别，不以重复标题去重。声骸分界以下不进入材料需求。
- [ ] 回放原分辨率及等比例1080p，加入头像、新、选中框干扰；截图非完整底部时complete必须false。运行 `TestMaterialVision.py` 并提交。

## 任务5：培养页和周扫描交互

**文件：** `src/task/MaterialPlannerTask.py`、`tests/TestMaterialPlannerTask.py`，`config.py`只按现有任务注册方式注册扫描入口。

**接口：** `scan_target(profile_id) -> dict`；`scan_inventory(profile_id, *, groups=None) -> dict`；`ensure_weekly_inventory(profile_id, now) -> dict`；`inspect_inventory_cell(cell) -> dict`。groups=None全仓库，否则只更新指定组的完整局部快照，不能标记完成全量周扫描。

- [ ] 使用 `WWOneTimeTask` 与 `BaseWWTask` 的现有组合模式创建任务，先super，再配置元数据。OCR/点击/滚动只走ok-script执行器；复用当前账号验证和停止检查。
- [ ] 目标入口定位用F2、双剑页签和培养目标文字；仓库用B和资源页签。不把材料页面某组的固定行号写死。
- [ ] 每次扫描先置顶并等待稳定帧，以保留部分重叠的距离滚动；连续无位移时结合底部布局判定结束；达到扫描上限或页面丢失保存partial，不写周完成标记。
- [ ] 未识别格子点击后读取右侧名称与拥有数量，并验证大图/名称对应刚选格子。右侧仍为旧名称时等待或失败，不沿用旧值。
- [ ] 测试一周只全扫一次、失败重试、周一缺席周二补扫、两个账号分别扫、局部扫不覆盖周标记、周日窗口不触发多余全扫。

```python
def test_partial_scan_retries_same_week(self):
    self.task.scan_inventory = self.partial_then_complete_scan
    self.task.ensure_weekly_inventory(self.profile, self.monday)
    self.task.ensure_weekly_inventory(self.profile, self.monday)
    self.assertEqual(self.scan_calls, 2)
```

- [ ] 运行 `TestMaterialPlannerTask.py`。人工实机确认F2/B入口和到达底部后再标交互完成；静态图通过不等于自动导航通过。

## 任务6：一次领取、多帧结算和实际奖励份数

**文件：** `MaterialPlannerTask.py`、`DomainTask.py`、`model.py`、`tests/TestMaterialIntegration.py`。

**接口：** `count_reward_units(drops, target_group) -> int | None`；`summarize_target(drops, target_group) -> Counts`；任务提供 `begin_reward_capture(profile_id, target_revision, group_id) -> str` 和 `capture_reward(claim_id, confirmed_stamina) -> Settlement`；`confirmed_stamina`为int或None。

- [ ] 凝素领取前持久化claim_id，调用现有use_stamina确认扣除。领取后先采集，再执行原有“是否继续”分支，因此最后一次体力用完也会抓全收益。

```python
# 拟接入DomainTask的顺序；capture为当前已绑定账号的MaterialPlannerTask。
claim_id = capture.begin_reward_capture(profile_id, target_revision, group_id)
can_continue, used = self.use_stamina(
    once=self.stamina_once, must_use=must_use, allow_backup=allow_backup)
if used > 0:
    result = capture.capture_reward(claim_id, used)
    # capture_reward必须在返回前确认图片与解析持久化；部分结果停止自动重开。
    if not result.complete:
        can_continue = False
```

- [ ] `use_stamina`抛异常但已见结算时，补采集并传None保存，禁止重复领取；无领取且used=0时给claim记录未领取状态，不构造零收益样本。
- [ ] 捕获过程等待动画稳定，从顶部完整滚动到底，先落原图再解析；补帧最多3次，对齐仍歧义保存partial并退出重开流程。超时要低于画面自动退出时间，使用现有停止检查。
- [ ] count_reward_units仅按独立绝对位置且目标组绿色计数；没有完整列表由调用者禁止产出有效份数。数量×7与×6合计13但份数2；不看双倍角标，不做活动识别。
- [ ] 测试领取末次、相同掉落不同领取、两个完全相同绿色格子、四绿色格子、绿色怪物排除、重叠多解、识别中止、保存失败、扣费未确认和重启恢复。恢复只查未完成claim并复核当前页面，不能自动重领。
- [ ] 运行新集成测试和 `TestStaminaAccounting.py`、`TestDomainRecoveryLoop.py`；功能关闭应完全走原流程。

## 任务7：按材料目标执行、周本回退和声骸衔接

**文件：** `MaterialPlannerTask.py`、`ForgeryTask.py`、`BaseWWTask.py`、`DailyTask.py`、`WeeklyBossTask.py`、`weekly_boss.py`；相应现有测试和 `TestMaterialIntegration.py`。

**接口：** `run_plan(profile_id) -> dict` 返回 `state、reason、target_revision`；`resolve_forgery_entry(group_id) -> dict`返回已验证入口及武器类型；`resolve_weekly_target(explicit_key, observed_entries) -> str | None`；`BaseWWTask.use_stamina(..., max_claims=None)`追加可选参数，原默认行为不变。`ForgeryTask.farm_forgery(..., planner=None)`追加可选上下文，不能持有其他账号上下文。

- [ ] 配置 `Material Planner Enabled` 默认false，按现有账号字段机制保存；启用后才执行新调度。仍以已验证profile_id运行，不读取无账号绑定的共享目标。
- [ ] 根据十组图标及武器类型解析凝素入口，20项顺序仅辅助。核验失败不以同武器的另一组代替。已有固定serial可以继续用于非规划旧任务。
- [ ] 每次校验目标修订和相关实际库存，四档缺口为零切下一组；有任何未知则补扫，不作完成。首版每次领取后复核当前组，后续均值阶段才降低频率。
- [ ] 接入max_claims=1限制单次40，默认上限2允许80；不得仅设置must_use=40期待正确限制，因为原实现的备用体力及预算分支需要统一上限。测试80可用但上限1、备用体力禁用、每日预算不足、实际扣费失败。
- [ ] 周本的“自动/未指定”与“明确禁用”分开；显式目标仍复用 `run_for_target`。自动选游戏列表首个已识别周本；明确错误目标报错不回退；剩余0展示待下周且继续其他材料。
- [ ] 共鸣者突破和怪物缺口不进入执行队列；已支持声骸无音区按设计默认规则衔接，材料完毕仍有预算才继续。更换角色/武器创建新目标修订，停止旧组并重新规划。
- [ ] 使用现有每日运行阶段信息展示原因：材料可满足、库存未知、周本次数耗尽、当前体力不足、入口未支持。停止原因不统一写成“体力已用完”。
- [ ] 运行 `TestWeeklyDailyIntegration.py`、`TestWeeklyBossTask.py`、`TestForgeryDomainLabels.py`、`TestMultiAccountDailyTask.py` 及新增集成用例。不能把“目标满足”写成“本周0/3”。

## 任务8：查询展示和均值统计

**文件：** `model.py`、`repository.py`、`MaterialPlannerTask.py`、`account_field_metadata.py`及实际注册所需账号UI文件；`TestMaterialModel.py`、`TestMaterialRepository.py`。

**接口：** `aggregate_settlements(records: list[Settlement]) -> dict`；`MaterialRepository.list_settlements(profile_id, group_id=None) -> list[Settlement]`，查询每claim最新有效修订；`export_csv(profile_id, destination) -> str`。返回统计字段 `claims、reward_units、stamina、counts、equivalent、per_unit、per_stamina、incomplete_claims`。

- [ ] 实现累计数量除累计份数及累计体力，分母0返回None。不将每场均值无权平均，不从体力推测份数。

```python
def test_weighted_average(self):
    # 两条记录：1份掉落30绿；2份掉落90绿。
    stats = aggregate_settlements(self.records)
    self.assertEqual(stats['reward_units'], 3)
    self.assertEqual(stats['per_unit'], 40)
```

- [ ] 每份统计与每体力统计各自过滤：体力未知但完整掉落/份数已知可进入每份统计，不进入每体力分子或分母。解析partial不进入任何收益均值，仍在总记录及异常列表显示。
- [ ] 展示当前目标、分品质库存/需求/缺口、周扫描时间、周本行、奖励份数、累计体力、均值、有效记录数。CSV按账号导出明细含claim_id和revision，可追溯原图。
- [ ] 材料字典未识别的收益归unknown保持原图，后续字典更新可离线新建解析修订；统计不重复计算旧修订。
- [ ] 均值自动决策保持关闭。预留后续纯函数估算（不接入领奖控制）：按四档平均掉落模拟候选份数，再calculate_gap判断方向可满足；不能只用总E判断低档充足。没有低档平均掉落时返回无法估计。
- [ ] 收敛配置数量，首版无需“活动模式”或“截图张数=份数”参数。新增文案按ok-script-i18n规范更新；统计报表不输出账号登录凭据。

## 任务9：实机验收、回归和发布

**文件：** 上述测试，新增 `docs/reviews/2026-09-11-material-planner-acceptance.md`（由实施时创建，时间按实际验收更新），修改 `config.py`及项目当前发布说明文件。

- [ ] 用给定两张实际结算跑完整OCR/图标/拼接管线，核对22格、目标2绿色格、13/16/3/0、88。单纯注入人工OCR的用例不能替代真实回放。
- [ ] 取得40体力一份、绿色四格、目标切换、未知材料、零库存、周本未指定、列表底部实机证据；核实绿色格计数规则在各支持难度保持成立。若不成立保留unknown，不伪造通过。
- [ ] 同账号完成周全扫、凝素领取、两帧结算、保存、重启读统计；再切另一个账号，验证无库存/目标串用。保持当前账号切换实现及已有验证守卫。
- [ ] 模拟磁盘写失败、程序中断、重试、停止、死亡恢复；历史数据库和原图不得减少，不得产生第二次领取；未完成记录不进入均值。
- [ ] 逐个运行定向测试后进行项目完整测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -p "Test*.py"`。执行前确认该命令与届时仓库测试入口兼容；记录已有失败和环境依赖，不能把未执行记通过。
- [ ] 验收文档逐项写“通过/失败/未验收”及证据路径、提交SHA、识别版本和样本数，不能以大量合成图代替游戏真实交互。
- [ ] 完成实现且验证后，按届时版本递增次版本并归零补丁号（若仍1.58.00则1.59.00），同步产品版本和说明。按deploy技能核对发布remote，创建匹配注释标签并推送分支与标签；用户若要求本地则不推。不得发布未验收的自动消费路径。

## 3. 阶段交付与停止界线

| 阶段 | 完成条件 | 可交付内容 |
|---|---|---|
| A：数据基础（1—5） | 实际页面读取及存储验收 | 手动扫描和真实缺口，不自动刷取 |
| B：收益统计（6、8） | 多帧完整性、份数和永久保存验收 | 复用已有刷本的结算统计，均值只展示 |
| C：自动规划（7、9） | 账号/体力/周本/声骸完整回归 | 按需刷取、周本回退、声骸衔接 |
| D：均值预测（后续） | 累积实际样本并在留出数据测误差 | 允许远离目标时批量预测，临近目标复核 |

阶段D不随意设“100次足够”的魔法阈值。先报告独立结算数、总份数、四品质均值和波动，在时间上留出的后续样本评估欠刷/过刷；经过用户接受的误差范围后才启用。期间一律持续保留原始统计资料。

## 4. 文档自检记录

- 已覆盖最新更正：周本不扫仓库、共鸣者突破仅记录、通用不抵扣、正常80体力可两份、绿色格数计份、不检测活动。
- 已区分二十入口与十材料组，不依赖凝素副本名称，不假定固定品质位置。
- 已覆盖数据永久保留、纠错修订、幂等、跨账号和多帧相同物品不能误去重。
- 真实操作未知项列为明确验收门槛；所有新接口在本文声明，尚未写入程序。
- 本文不要求现在执行编码、消耗体力或创建自动化。
