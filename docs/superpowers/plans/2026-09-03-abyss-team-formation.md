# 自动深渊单队编排与点击 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 自动深渊在识别角色、体力和等级后，按两组固定预设选出一支三人队，清理快速编队页已有选择，实际点击三名角色并验证 `1/2/3`，点击“完成”后停在编辑队伍页。

**Architecture:** 新增一个不依赖 GUI 的纯编队规划模块，固定预设、角色身份、定位和替补保护规则全部在该模块中完成；`AutoAbyssTask` 只负责画面识别、跨页定位、点击和页面状态验证。继续复用现有角色库、ORB 头像识别、OCR、OpenCV、滚动保护和任务状态窗口，不新增依赖，不引入自动战斗或多队调度。

**Tech Stack:** Python 3.11、dataclasses、OpenCV、NumPy、ok-script 任务/截图/OCR/点击接口、unittest、PowerShell、Git。

**Spec:** `docs/superpowers/specs/2026-09-03-abyss-team-formation-design.md`

## Global Constraints

- 只支持当前中文 PC 客户端和 16:9 的 1920×1080、2560×1440 布局。
- 只组成一支队伍；不进入战斗，不点击“开启挑战”，不安排后续楼层，不预测或扣减体力。
- 只有 `energy > 0` 且 `level > 60` 的角色可以参与规划。
- 第二队列完整队高于第一队列两人加替补；第一、第二队列同时完整时选择第一队列。
- 替补永不拆完整队；存在普通候选时不拆其他两人核心。
- `Rover:Spectro` 与 `Rover:Aero` 严格区分，`rover_unknown` 不得完成光主或风主预设。
- 已有选择必须先通过 `1/2/3` 标记检查并清除；编号冲突、清除失败、选择失败或页面验证失败均停止。
- 不增加角色选择配置页、预设编辑器、持久化扫描结果或第三方依赖。
- 代码变更使用中等版本 `1.27.00`，同步 `config.py`、About、更新日志、发布测试、注释标签和 GitHub。
- 所有自动验证均为离线测试；禁止启动或操控游戏，真实点击由用户在打包版上手动验证。
- Python 命令必须直接使用 `E:\AI work\ok-wuthering-waves-master\.venv\Scripts\python.exe`。

## File map

- Create `src/task/abyss_team_planner.py`: 稳定身份常量、两组固定预设、不可变规划结果、定位查询和纯编队算法。
- Create `tests/TestAbyssTeamPlanner.py`: 完整队优先、队列优先、核心保护、替补定位、主角形态和三人不足测试。
- Modify `src/task/AutoAbyssTask.py`: 扫描记录扩展、主角元素分类、选择编号识别、跨页清理/选择/完成和状态输出。
- Modify `tests/TestAutoAbyssTask.py`: 离线视觉分类、编号识别、清理、点击顺序、重试、跨页和安全终点测试。
- Modify `tests/TestTaskNavigationClassification.py`: 更新任务边界文案断言，继续禁止 `AutoCombatTask`。
- Modify `run_tests.ps1`: 把新规划测试加入 unit 组。
- Modify `config.py`, `custom_ok/ok/gui/about/AboutTab.py`, `更新日志.md`, `tests/TestReleaseReadiness.py`: 同步 `1.27.00` 发布信息。
- No change `打包更新.py`: 它已递归包含整个 `src/`，新规划模块会自动进入更新包。

---

### Task 1: 建立纯编队规划器和完整优先规则

**Files:**
- Create: `src/task/abyss_team_planner.py`
- Create: `tests/TestAbyssTeamPlanner.py`
- Modify: `run_tests.ps1:10-25`

**Interfaces:**
- Consumes: 扫描记录属性 `character_id`, `energy`, `level`, `confidence`, `rover_form`；`src.char.CharFactory.char_dict` 中的 `char_type`。
- Produces: `TeamPreset`, `TeamPlan`, `TEAM_PRESETS`, `ROVER_SPECTRO`, `ROVER_AERO`, `ROVER_HAVOC`, `ROVER_UNKNOWN`, `effective_character_id(record)`, `role_for_character(character_id)`, `plan_team(records)`。

- [ ] **Step 1: 写规划模型和优先级的失败测试**

  创建 `tests/TestAbyssTeamPlanner.py`，使用 `SimpleNamespace` 构造离线扫描记录，至少写入以下精确场景：

  ```python
  # -*- coding: utf-8 -*-
  import unittest
  from types import SimpleNamespace

  from src.Labels import Labels
  from src.task.abyss_team_planner import (
      ROVER_AERO,
      ROVER_SPECTRO,
      ROVER_UNKNOWN,
      effective_character_id,
      plan_team,
  )


  def record(character_id, energy=10, level=90, confidence=0.9, rover_form=None):
      return SimpleNamespace(
          character_id=character_id,
          energy=energy,
          level=level,
          confidence=confidence,
          rover_form=rover_form,
      )


  class TestAbyssTeamPlanner(unittest.TestCase):
      def test_second_queue_complete_beats_first_queue_two_member_core(self):
          plan = plan_team([
              record(Labels.char_qingxiao),
              record(Labels.char_denia),
              record(Labels.char_galbrena),
              record(Labels.char_chouyuan),
              record(Labels.char_shorekeeper),
              record(Labels.char_verina),
          ])
          self.assertEqual(
              plan.members,
              (Labels.char_galbrena, Labels.char_chouyuan, Labels.char_shorekeeper),
          )
          self.assertTrue(plan.complete)
          self.assertEqual(plan.preset.queue, 2)

      def test_first_queue_complete_beats_second_queue_complete(self):
          plan = plan_team([
              record(Labels.char_qingxiao), record(Labels.char_denia), record(Labels.char_chisa),
              record(Labels.char_galbrena), record(Labels.char_chouyuan), record(Labels.char_shorekeeper),
          ])
          self.assertEqual(
              plan.members,
              (Labels.char_qingxiao, Labels.char_denia, Labels.char_chisa),
          )
          self.assertEqual(plan.preset.queue, 1)

      def test_qingxiao_core_uses_verina_for_missing_healer(self):
          plan = plan_team([
              record(Labels.char_qingxiao),
              record(Labels.char_denia),
              record(Labels.char_verina, energy=8, level=90),
          ])
          self.assertEqual(
              plan.members,
              (Labels.char_qingxiao, Labels.char_denia, Labels.char_verina),
          )
          self.assertEqual(plan.substitutions, ((Labels.char_chisa, Labels.char_verina),))
          self.assertFalse(plan.complete)
          self.assertTrue(plan.executable)

      def test_regular_candidate_does_not_break_another_two_member_core(self):
          plan = plan_team([
              record(Labels.char_qingxiao), record(Labels.char_denia),
              record(Labels.char_zani, energy=10), record(Labels.char_phoebe, energy=10),
              record(Labels.char_verina, energy=5),
          ])
          self.assertEqual(plan.members[-1], Labels.char_verina)
          self.assertNotIn(Labels.char_zani, plan.members)
          self.assertNotIn(Labels.char_phoebe, plan.members)

      def test_two_member_core_can_be_used_only_when_no_regular_candidate_exists(self):
          plan = plan_team([
              record(Labels.char_qingxiao), record(Labels.char_denia),
              record(Labels.char_zani, energy=8), record(Labels.char_phoebe, energy=10),
          ])
          self.assertTrue(plan.executable)
          self.assertIn(plan.members[-1], (Labels.char_zani, Labels.char_phoebe))
          self.assertTrue(plan.broke_two_member_core)

      def test_rover_forms_are_strict_and_unknown_never_completes_a_rover_preset(self):
          base = [record(Labels.char_zani), record(Labels.char_phoebe)]
          spectro = plan_team(base + [record(Labels.char_rover, rover_form=ROVER_SPECTRO)])
          aero = plan_team(base + [record(Labels.char_rover, rover_form=ROVER_AERO)])
          unknown = plan_team(base + [record(Labels.char_rover, rover_form=ROVER_UNKNOWN)])
          self.assertTrue(spectro.complete)
          self.assertEqual(spectro.members[-1], ROVER_SPECTRO)
          self.assertFalse(aero.complete)
          self.assertFalse(unknown.complete)
          self.assertEqual(effective_character_id(base[0]), Labels.char_zani)

      def test_fewer_than_three_usable_characters_returns_non_executable_plan(self):
          plan = plan_team([
              record(Labels.char_qingxiao),
              record(Labels.char_denia),
              record(Labels.char_verina, energy=0),
          ])
          self.assertFalse(plan.executable)
          self.assertEqual(len(plan.members), 2)


  if __name__ == "__main__":
      unittest.main()
  ```

- [ ] **Step 2: 运行新测试并确认因模块不存在而失败**

  Run:

  ```powershell
  & .\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestAbyssTeamPlanner.py
  ```

  Expected: FAIL with `ModuleNotFoundError: No module named 'src.task.abyss_team_planner'`.

- [ ] **Step 3: 实现不可变模型、完整预设和最小规划算法**

  在 `src/task/abyss_team_planner.py` 中实现：

  ```python
  @dataclass(frozen=True)
  class TeamPreset:
      queue: int
      members: tuple[str, str, str]
      display_names: tuple[str, str, str]


  @dataclass(frozen=True)
  class TeamPlan:
      preset: TeamPreset
      members: tuple[str, ...]
      matched: tuple[str, ...]
      substitutions: tuple[tuple[str, str], ...]
      complete: bool
      executable: bool
      broke_two_member_core: bool
      reason: str
  ```

  定义主角身份常量：

  ```python
  ROVER_SPECTRO = "rover_spectro"
  ROVER_AERO = "rover_aero"
  ROVER_HAVOC = "rover_havoc"
  ROVER_UNKNOWN = "rover_unknown"
  ```

  `TEAM_PRESETS` 必须按下面的数据一次性完整定义；普通角色使用 `Labels` 的规范首模板 ID，光主使用 `ROVER_SPECTRO`，风主使用 `ROVER_AERO`。数组顺序只用于稳定存放，不作为同队列业务优先级：

  ```python
  def _preset(queue, members, names):
      return TeamPreset(queue=queue, members=members, display_names=names)


  TEAM_PRESETS = (
      _preset(1, (Labels.char_qingxiao, Labels.char_denia, Labels.char_chisa),
              ("清宵", "达妮娅", "千咲")),
      _preset(1, (Labels.yangyang_sp, Labels.char_chisa, Labels.char_suisui),
              ("秧秧·玄翎", "千咲", "穗穗")),
      _preset(1, (Labels.char_hiyuki, Labels.char_lucilla, Labels.char_chisa),
              ("绯雪", "洛瑟拉", "千咲")),
      _preset(1, (Labels.char_hiyuki, Labels.char_lucilla, Labels.char_suisui),
              ("绯雪", "洛瑟拉", "穗穗")),
      _preset(1, (Labels.char_lucy, Labels.char_rebecca, Labels.char_moning),
              ("露西", "丽贝卡", "莫宁")),
      _preset(1, (Labels.char_aemeath, Labels.char_linnai, Labels.char_moning),
              ("爱弥斯", "琳奈", "莫宁")),
      _preset(1, (Labels.char_luhesi, Labels.char_linnai, Labels.char_moning),
              ("陆赫斯", "琳奈", "莫宁")),
      _preset(1, (Labels.char_luhesi, Labels.char_denia, Labels.char_moning),
              ("陆赫斯", "达妮娅", "莫宁")),
      _preset(1, (Labels.char_aemeath, Labels.char_denia, Labels.char_chisa),
              ("爱弥斯", "达妮娅", "千咲")),
      _preset(1, (Labels.char_xigelika, Labels.char_chouyuan, Labels.char_shorekeeper),
              ("西格莉卡", "仇远", "守岸人")),
      _preset(1, (Labels.char_xigelika, Labels.char_linnai, Labels.char_moning),
              ("西格莉卡", "琳奈", "莫宁")),
      _preset(2, (Labels.char_galbrena, Labels.char_chouyuan, Labels.char_shorekeeper),
              ("嘉贝莉娜", "仇远", "守岸人")),
      _preset(2, (Labels.char_galbrena, Labels.char_lupa, Labels.char_shorekeeper),
              ("嘉贝莉娜", "露帕", "守岸人")),
      _preset(2, (Labels.char_galbrena, Labels.char_iuno, Labels.char_shorekeeper),
              ("嘉贝莉娜", "尤诺", "守岸人")),
      _preset(2, (Labels.Augusta, Labels.char_iuno, Labels.char_shorekeeper),
              ("奥古斯塔", "尤诺", "守岸人")),
      _preset(2, (Labels.char_cartethyia, Labels.char_ciaccona, Labels.char_shorekeeper),
              ("卡提希娅", "夏空", "守岸人")),
      _preset(2, (Labels.char_cartethyia, Labels.char_ciaccona, ROVER_AERO),
              ("卡提希娅", "夏空", "风主")),
      _preset(2, (Labels.char_cartethyia, Labels.char_ciaccona, Labels.char_chisa),
              ("卡提希娅", "夏空", "千咲")),
      _preset(2, (Labels.char_phrolova, Labels.char_cantarella, Labels.char_shorekeeper),
              ("弗洛洛", "坎特蕾拉", "守岸人")),
      _preset(2, (Labels.char_phrolova, Labels.char_cantarella, Labels.char_roccia),
              ("弗洛洛", "坎特蕾拉", "洛可可")),
      _preset(2, (Labels.char_zani, Labels.char_phoebe, ROVER_SPECTRO),
              ("赞妮", "菲比", "光主")),
      _preset(2, (Labels.char_zani, Labels.char_phoebe, Labels.char_chisa),
              ("赞妮", "菲比", "千咲")),
      _preset(2, (Labels.char_zani, Labels.char_phoebe, Labels.char_shorekeeper),
              ("赞妮", "菲比", "守岸人")),
      _preset(2, (Labels.char_carlotta, Labels.char_zhezhi, Labels.char_shorekeeper),
              ("柯莱塔", "折枝", "守岸人")),
  )
  ```

  `effective_character_id(record)` 对 `Labels.char_rover`/`Labels.char_rover_male` 返回 `record.rover_form or ROVER_UNKNOWN`，其他角色返回 `record.character_id`。`role_for_character()` 对 `ROVER_SPECTRO` 返回 `CharType.SUB_DPS`、对 `ROVER_AERO` 返回 `CharType.HEALER`，其他角色从 `char_dict[id]["char_type"]` 读取。

  `plan_team(records)` 按以下可直接编码的键完成排序；预设没有任何命中时 `quality = (0, 0, 0)`，避免对空集合调用 `min()`：

  ```python
  quality = (
      min(record.energy for record in members),
      sum(record.level for record in members),
      sum(record.confidence for record in members),
  )
  full_key = (preset.queue, -quality[0], -quality[1], -quality[2], preset.members)
  partial_key = (-len(matched), preset.queue, -quality[0], -quality[1], -quality[2], preset.members)
  substitute_key = (-record.energy, -record.level, -record.confidence, effective_character_id(record))
  ```

  先过滤可用角色并建立身份到记录的唯一映射；同身份重复时保留 `(energy is not None, level is not None, confidence)` 最大者。存在完整预设时直接返回最佳完整队，不进入替补。不存在完整队时选择最佳交集预设，收集其他预设的两人核心作为第二层候选，但从保护集合中排除当前目标预设已经命中的成员；每个缺失槽位先从不受保护的同定位角色、普通任意定位、两人核心同定位、两人核心任意定位中依次取最优角色。任何其他完整队成员均不得进入替补候选。最终不足三人时返回 `executable=False`，不得抛异常。

- [ ] **Step 4: 把新测试加入 unit 组并验证规划器**

  在 `run_tests.ps1` 的 `unit` 文件列表中紧邻 `TestAutoAbyssTask.py` 加入 `TestAbyssTeamPlanner.py`，然后运行：

  ```powershell
  & .\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestAbyssTeamPlanner.py
  ```

  Expected: all planner tests PASS；当前账号用例输出 `清宵/达妮娅/维里奈` 对应的规范 ID。

- [ ] **Step 5: 提交纯规划器**

  ```powershell
  git add -- src/task/abyss_team_planner.py tests/TestAbyssTeamPlanner.py run_tests.ps1
  git commit -m "feat: plan automatic abyss teams"
  ```

---

### Task 2: 扩展角色扫描以识别主角形态和选择编号

**Files:**
- Modify: `src/task/AutoAbyssTask.py:43-55, 542-684`
- Modify: `tests/TestAutoAbyssTask.py:1-108, 245-269`

**Interfaces:**
- Consumes: Task 1 的主角身份常量和 `effective_character_id()`。
- Produces: `CharacterScanRecord.rover_form`, `rover_confidence`, `selection_number`; `classify_rover_element_crop(crop)`; `parse_selection_number(text)`; `_read_selection_number(frame, slot)`。

- [ ] **Step 1: 写主角 HSV 分类和 `1/2/3` 标记的失败测试**

  在 `tests/TestAutoAbyssTask.py` 加入：

  ```python
  def test_rover_element_colour_classifier_is_strict(self):
      yellow = np.full((80, 80, 3), (20, 220, 240), dtype=np.uint8)
      green = np.full((80, 80, 3), (90, 220, 120), dtype=np.uint8)
      purple = np.full((80, 80, 3), (180, 80, 220), dtype=np.uint8)
      gray = np.full((80, 80, 3), 120, dtype=np.uint8)
      self.assertEqual(classify_rover_element_crop(yellow)[0], ROVER_SPECTRO)
      self.assertEqual(classify_rover_element_crop(green)[0], ROVER_AERO)
      self.assertEqual(classify_rover_element_crop(purple)[0], ROVER_HAVOC)
      self.assertEqual(classify_rover_element_crop(gray)[0], ROVER_UNKNOWN)

  def test_selection_number_accepts_only_one_two_three(self):
      self.assertEqual(parse_selection_number("1"), 1)
      self.assertEqual(parse_selection_number(" 3 "), 3)
      self.assertIsNone(parse_selection_number("10"))
      self.assertIsNone(parse_selection_number("Lv.90"))
  ```

  扩展现有 1080P/1440P 清宵扫描用例：当合成图右上角画出高饱和亮色 `1` 时断言 `records[0].selection_number == 1`；无标记时断言为 `None`。数字必须画在角色卡局部 `(0.70, 0.02)-(0.98, 0.28)` 内。

- [ ] **Step 2: 运行 AutoAbyss 测试并确认新接口缺失**

  ```powershell
  & .\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestAutoAbyssTask.py
  ```

  Expected: FAIL because classifier, parser and record fields do not exist.

- [ ] **Step 3: 扩展扫描记录且保持旧调用兼容**

  在 `CharacterScanRecord` 末尾添加带默认值字段，保证现有七参数位置构造不变：

  ```python
  rover_form: str | None = None
  rover_confidence: float = 0.0
  selection_number: int | None = None
  ```

  `merge_character_records()` 继续用原质量规则选择头像/体力/等级最佳记录，不把未知主角转换为光主或风主；规划阶段统一调用 `effective_character_id()`。

- [ ] **Step 4: 实现保守的主角元素颜色分类**

  `classify_rover_element_crop(crop)` 先转 HSV，使用 `S >= 70`、`V >= 70` 的有效彩色像素，然后统计三个互斥色相区间：衍射黄 `H=15..42`、气动绿 `H=43..95`、湮灭紫 `H=125..165`。有效彩色像素不足裁剪面积 `3.5%`、获胜区间占有效色像素小于 `55%`，或第一名比第二名少于 `15` 个百分点时，返回 `(ROVER_UNKNOWN, confidence)`；其余返回形态和获胜占比。

  `_recognize_character_screen()` 只有在 ORB 识别结果为主角规范 ID 时，才裁剪角色卡左上角 `(0.02, 0.02, 0.28, 0.28)` 并分类。未知时执行：

  ```python
  self.log_warning(f"主角元素形态不确定：第{screen_index}屏槽位{slot_index}，置信度{confidence:.2f}")
  self.screenshot(f"abyss_rover_form_unknown_p{screen_index}_s{slot_index}", frame=frame)
  ```

  不得把角色库目前的 `HavocRover` 类名当作形态证据。

- [ ] **Step 5: 实现右上角选择编号读取**

  `parse_selection_number(text)` 只接受去空白后完全等于 `"1"`, `"2"`, `"3"`。`_read_selection_number(frame, slot)` 裁剪角色卡局部 `(0.70, 0.00, 1.00, 0.30)`，转 HSV 后保留 `S >= 80` 且 `V >= 140` 的像素，把掩码扩边并放大 4 倍后调用现有 OCR；仅返回 `1..3`，其他文字忽略。

  `_recognize_character_screen()` 将主角形态、形态置信度和选择编号写入每个记录；日志追加当前屏发现的选择编号，例如 `选择标记 1:清宵, 2:达妮娅`。

- [ ] **Step 6: 运行扫描回归并提交**

  ```powershell
  & .\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestAutoAbyssTask.py
  git add -- src/task/AutoAbyssTask.py tests/TestAutoAbyssTask.py
  git commit -m "feat: recognize abyss team selection state"
  ```

  Expected: AutoAbyss 离线测试全部 PASS；1080P/1440P 原头像、体力、等级测试继续通过。

---

### Task 3: 实现跨页清理、按顺序点击和编号验证

**Files:**
- Modify: `src/task/AutoAbyssTask.py:415-491, 640-684`
- Modify: `tests/TestAutoAbyssTask.py:188-282`

**Interfaces:**
- Consumes: `TeamPlan.members` 的三个稳定身份、原始 `CharacterScanRecord` 定位、现有滚动变化保护。
- Produces: `validate_selection_state(records)`, `character_safe_click(slot)`, `_show_character_page(page_index)`, `_clear_all_selection()`, `_select_planned_team(plan, records)`, `_finish_team_formation()`。

- [ ] **Step 1: 写纯选择状态和安全点击点测试**

  添加测试：

  ```python
  def test_selection_state_allows_overlap_but_rejects_conflicts(self):
      same = [
          CharacterScanRecord("a", "A", 10, 90, .9, 1, 0, selection_number=1),
          CharacterScanRecord("a", "A", 10, 90, .8, 2, 7, selection_number=1),
      ]
      self.assertEqual(validate_selection_state(same), {1: "a"})
      with self.assertRaisesRegex(ValueError, "编号 1"):
          validate_selection_state(same + [
              CharacterScanRecord("b", "B", 10, 90, .9, 1, 1, selection_number=1),
          ])

  def test_character_safe_click_avoids_number_energy_and_level(self):
      x, y = character_safe_click(character_card_slots()[0])
      self.assertAlmostEqual(x, CHARACTER_CARD_X + CHARACTER_CARD_WIDTH * 0.50)
      self.assertAlmostEqual(y, CHARACTER_CARD_Y[0] + CHARACTER_CARD_HEIGHT * 0.35)
  ```

  `validate_selection_state()` 还要拒绝同一身份同时对应两个编号；重复屏重叠导致的同身份同编号允许合并。

- [ ] **Step 2: 写离线编排控制器失败测试**

  用 `AutoAbyssTask.__new__()` 和 lambda 替换截图、翻页、头像校验、编号读取及点击，覆盖以下调用序列：

  1. 初始无选择时按 plan 槽位顺序点击，验证期望编号依次为 `1,2,3`。
  2. 初始已有 `1,2` 时先点击对应卡片取消，确认全部页面无编号后才开始新选择。
  3. 目标分布在第 1、2、1 屏时，翻页序列准确且选择顺序仍为 `1,2,3`。
  4. 第一次编号未出现时重新验证身份并重试一次；第二次失败时调用清理并抛出“角色选择编号验证失败”。
  5. 同一编号对应两个角色时，不产生任何点击并保存诊断截图。

  每个测试只断言公开的调用事件列表，例如：

  ```python
  self.assertEqual(events, [
      ("show", 1), ("click", "char_a"), ("expect", "char_a", 1),
      ("show", 2), ("click", "char_b"), ("expect", "char_b", 2),
      ("show", 1), ("click", "char_c"), ("expect", "char_c", 3),
  ])
  ```

- [ ] **Step 3: 运行测试确认跨页控制接口尚未实现**

  ```powershell
  & .\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestAutoAbyssTask.py
  ```

  Expected: new selection controller tests FAIL; existing scan tests remain PASS.

- [ ] **Step 4: 实现统一翻页，不复制单页/多页逻辑**

  `_scan_character_pages()` 设置：单页为 `self._character_page_count = 1`, `self._character_page_index = 1`；多页扫描结束为 `count = 2`, `index = 2`。

  `_show_character_page(page_index)` 仅接受 `1..self._character_page_count`。目标与当前页相同直接返回稳定帧；向第一页使用 `scroll_relative(0.50, 0.50, 10)`，向第二页使用 `-10`。每次滚动后复用 `frame_change_score()` 和 `scroll_thumb_center()` 验证变化，失败时强制前台再重试一次；仍失败保存 `abyss_character_page_{page_index}_failed` 并抛出异常。单页请求第二页直接拒绝。

- [ ] **Step 5: 实现身份复核和已有选择清理**

  `character_safe_click(slot)` 返回卡片主体 `(x + width*0.50, y + height*0.35)`。点击前 `_verify_record_identity(frame, record)` 必须重新裁剪头像并调用 `_identify_character()`；主角还要重新分类形态，结果必须与 `effective_character_id(record)` 完全相等。

  `_selection_numbers_on_page(frame)` 对所有当前可见完整槽位读取编号；单页允许读取底部不完整行。`_clear_all_selection()` 的流程固定为：

  1. 扫描所有页面并运行 `validate_selection_state()`；冲突立即截图和停止。
  2. 按页面和编号排序，复核身份后点击每个已选卡片。
  3. 每次点击后等待同槽位编号消失，最长 2 秒。
  4. 再扫描所有页面，只有三个编号都不存在才返回。

  清理失败保存 `abyss_character_selection_clear_failed`，不得继续选择。

- [ ] **Step 6: 实现三次选择、单次重试和失败回滚**

  `_select_planned_team(plan, records)` 必须先确认 `plan.executable` 且 `len(plan.members) == 3`。对每个身份从原始记录中选择最佳点击位置：完整卡片优先、置信度高优先、第一页优先、槽位小优先。严格按 `plan.members` 顺序执行：翻到记录页、复核身份、点击安全点、等待同槽位出现对应的 `1/2/3`。

  单个角色第一次失败时只重试一次；第二次失败执行 `_clear_all_selection()`，保存 `abyss_character_select_{number}_failed` 并抛出异常。第三个成功后扫描全部页面并运行 `validate_selection_state()`，最终映射必须精确等于 `{1: member0, 2: member1, 3: member2}`。

- [ ] **Step 7: 实现“完成”按钮和安全终点**

  `_finish_team_formation()` 仅允许点击精确 OCR 的 `完成`：

  ```python
  complete = self._wait_exact_text_or_fail(
      "完成", (0.76, 0.84, 0.97, 0.99), 6, "未找到快速编队页面右下角的完成按钮"
  )
  self.click_box(complete, after_sleep=1)
  self._wait_exact_text_or_fail("编辑队伍", (0.01, 0.01, 0.22, 0.16), 8, "完成后未返回编辑队伍页")
  self._wait_exact_text_or_fail("开启挑战", (0.75, 0.82, 0.98, 0.98), 4, "编辑队伍页面结构异常")
  ```

  不保存或点击“开启挑战”的 OCR box。离线测试必须断言唯一点击对象是“完成”。

- [ ] **Step 8: 运行控制器回归并提交**

  ```powershell
  & .\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestAutoAbyssTask.py
  git add -- src/task/AutoAbyssTask.py tests/TestAutoAbyssTask.py
  git commit -m "feat: select and verify abyss team"
  ```

  Expected: 清理、单页、多页、重试和安全终点测试全部 PASS，测试期间没有窗口或游戏操作。

---

### Task 4: 把规划和点击接入自动深渊任务状态流

**Files:**
- Modify: `src/task/AutoAbyssTask.py:237-299, 382-433`
- Modify: `tests/TestAutoAbyssTask.py`
- Modify: `tests/TestTaskNavigationClassification.py:12-19`

**Interfaces:**
- Consumes: `plan_team(available_records) -> TeamPlan` 和 Task 3 的清理/选择/完成方法。
- Produces: `_format_team_plan(plan, records) -> str`；完整运行阶段“生成编队计划→清理已有编队→选择角色 1/2/3→完成编队”。

- [ ] **Step 1: 写任务集成和状态输出的失败测试**

  在 `tests/TestAutoAbyssTask.py` 构造一个无 GUI 的 task，替换导航和扫描方法，让 `_enter_and_scan_characters()` 返回清宵、达妮娅、维里奈；记录 `info_set`, `_set_status`, `_clear_all_selection`, `_select_planned_team`, `_finish_team_formation` 调用。断言：

  ```python
  self.assertIn("清宵", info["编队计划"])
  self.assertIn("达妮娅", info["编队计划"])
  self.assertIn("维里奈替补千咲", info["编队计划"])
  self.assertEqual(actions, ["clear", "select", "finish"])
  self.assertEqual(statuses[-1][0], "编队完成")
  ```

  再写不足三人用例，断言状态为“无法组成三人队”、actions 为空，并且任务停留在角色列表。

- [ ] **Step 2: 运行测试确认 run() 仍只扫描不编队**

  ```powershell
  & .\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestAutoAbyssTask.py
  ```

  Expected: integration tests FAIL because `run()` has not called planner/controller.

- [ ] **Step 3: 接入规划和点击阶段**

  在 `run()` 中保留现有三塔扫描、角色两屏扫描、账号内存缓存和“可用角色”输出；在 `merged, available` 后依次执行：

  ```python
  plan = plan_team(available)
  plan_text = self._format_team_plan(plan, merged.values())
  self.info_set("编队计划", plan_text)
  if not plan.executable:
      self._set_status("无法组成三人队", plan_text)
      raise Exception(f"可用角色不足三人：{plan_text}")
  self._set_status("清理已有编队", "正在检查并清除快速编队页已有的 1/2/3")
  self._clear_all_selection()
  self._set_status("选择编队", plan_text)
  self._select_planned_team(plan, records)
  self._set_status("确认编队", "三个选择编号验证成功，正在点击完成")
  self._finish_team_formation()
  self._set_status("编队完成", f"{plan_text}；已停在编辑队伍页")
  ```

  `_format_team_plan()` 用原扫描记录的 `display_name` 显示完整队、命中人数、替补关系和最终 `1/2/3`，不把 `char_*` 内部 ID 暴露给用户。当前账号文本必须包含“第一队列；命中2/3；清宵 / 达妮娅 / 维里奈；维里奈替补千咲”。

- [ ] **Step 4: 更新任务名称、说明和导航安全测试**

  名称改为 `🧪 自动深渊：扫描与自动编队`。说明明确“会在快速编队页选择三名角色并点击完成，随后停在编辑队伍页；不会点击开启挑战，不会进入战斗”。启动日志使用相同安全边界。

  `tests/TestTaskNavigationClassification.py` 继续断言 `navigation_section == "tests"`、说明包含“不会进入战斗”、源码不包含 `AutoCombatTask`；新增断言说明包含“不会点击开启挑战”。

- [ ] **Step 5: 运行聚焦测试并提交集成**

  ```powershell
  & .\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestAbyssTeamPlanner.py
  & .\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestAutoAbyssTask.py
  & .\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestTaskNavigationClassification.py
  git add -- src/task/AutoAbyssTask.py tests/TestAutoAbyssTask.py tests/TestTaskNavigationClassification.py
  git commit -m "feat: form one abyss team automatically"
  ```

  Expected: three focused files PASS；没有测试调用真实截图、真实窗口、输入设备或游戏。

---

### Task 5: 发布 `1.27.00`、生成更新包并推送 GitHub

**Files:**
- Modify: `config.py:21`
- Modify: `custom_ok/ok/gui/about/AboutTab.py:49`
- Modify: `更新日志.md:5`
- Modify: `tests/TestReleaseReadiness.py:16`
- Generated/ignored: `E:\game\okww owener\okww_更新包_20260903.zip`

**Interfaces:**
- Consumes: Task 1-4 已通过的离线实现。
- Produces: 固定宽度版本 `1.27.00`、注释标签 `v1.27.00`、GitHub 分支/标签、目标打包目录中的最新更新包。

- [ ] **Step 1: 先写发布版本失败断言**

  将 `tests/TestReleaseReadiness.py` 的固定版本期望改为：

  ```python
  self.assertEqual(version, "1.27.00")
  ```

  并加入新版本主题断言：`自动编队`, `1/2/3`, `不会点击开启挑战` 必须同时存在于 `更新日志.md` 和 `AboutTab.py`。

- [ ] **Step 2: 运行发布测试并确认旧版本失败**

  ```powershell
  & .\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestReleaseReadiness.py
  ```

  Expected: FAIL because `config.py` is still `1.26.02` and release notes have no `1.27.00` entry.

- [ ] **Step 3: 同步产品版本和发布说明**

  把 `config.py` 更新为 `version = "1.27.00"`。About 首行和更新日志顶端新增相同事实：两队列完整队优先、两人核心和替补保护、主角形态严格区分、清理已有选择、逐次验证 `1/2/3`、点击“完成”并停在编辑队伍页；明确离线验证未启动或操控游戏。

- [ ] **Step 4: 运行语法、聚焦、unit 和全仓回归**

  ```powershell
  & .\.venv\Scripts\python.exe -m compileall -q src tests
  & .\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestAbyssTeamPlanner.py
  & .\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestAutoAbyssTask.py
  & .\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestTaskNavigationClassification.py
  & .\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestReleaseReadiness.py
  powershell -ExecutionPolicy Bypass -File .\run_tests.ps1 -Group unit
  powershell -ExecutionPolicy Bypass -File .\run_tests.ps1 -Group all
  ```

  Expected: compileall exit 0；所有聚焦测试、unit 和完整测试组 PASS。任何失败先修复根因并重跑对应命令，不启动游戏补验证。

- [ ] **Step 5: 验证版本、差异和发布标签**

  ```powershell
  & .\.venv\Scripts\python.exe .\scripts\validate_release.py --tag v1.27.00
  git diff --check
  git status --short
  git diff --stat
  ```

  Expected: validator prints `1.27.00`；无空白错误；变更只包含本计划列出的源码、测试、版本与文档文件。

- [ ] **Step 6: 生成并审计目标打包版更新包**

  ```powershell
  & .\.venv\Scripts\python.exe .\打包更新.py 'E:\game\okww owener'
  & .\.venv\Scripts\python.exe .\scripts\package_smoke.py --dist 'E:\game\okww owener'
  & .\.venv\Scripts\python.exe -c "import zipfile; p=r'E:\game\okww owener\okww_更新包_20260903.zip'; z=zipfile.ZipFile(p); n=set(x.replace('\\','/') for x in z.namelist()); required={'src/task/abyss_team_planner.py','src/task/AutoAbyssTask.py','config.py','custom_ok/ok/gui/about/AboutTab.py','更新日志.md'}; assert required <= n; assert not any(x.startswith(('logs/','screenshots/','working/')) for x in n); print(len(n))"
  ```

  Expected: 更新包生成成功；smoke PASS；新规划器和任务源码均在包内，账号配置、日志、截图不在包内。不得启动目标目录中的程序或游戏。

- [ ] **Step 7: 提交最终发布元数据**

  ```powershell
  git add -- config.py custom_ok/ok/gui/about/AboutTab.py 更新日志.md tests/TestReleaseReadiness.py
  git commit -m "chore: release automatic abyss formation 1.27.00"
  git status --short
  ```

  Expected: working tree clean；更新包保持 Git 忽略，不进入提交。

- [ ] **Step 8: 创建注释标签并推送正确仓库**

  ```powershell
  git tag -a v1.27.00 -m "okww 1.27.00 automatic abyss team formation"
  git push origin codex/account-switch-foreground-bitblt
  git push origin v1.27.00
  git ls-remote --heads origin codex/account-switch-foreground-bitblt
  git ls-remote --tags origin v1.27.00
  ```

  Expected: `xihuojun2020-tech/okww-custom.git` 上的分支指向本地 HEAD，远端存在新的 `v1.27.00` 注释标签；不得修改或移动 `v1.26.02` 等历史标签。

## Manual verification handoff

实现与离线发布完成后，由用户在打包版手动启动“自动深渊：扫描与自动编队”。建议先使用已知会得到 `清宵 + 达妮娅 + 维里奈` 的账号，确认程序会清除旧编号、依次出现 `1/2/3`、点击“完成”并停在编辑队伍页。若失败，只需提供本次 `logs/`、自动保存的 `abyss_*` 诊断截图和当时分辨率；程序本身不得自动点击“开启挑战”。
