# 自动深渊三塔完整流程 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 自动扫描并挑战逆境深塔的三座塔，按设置决定顺序，按剩余关卡体力预算重新组队，并正确处理继续挑战、塔完成与失败。

**Architecture:** 纯函数负责顺序、楼层和体力计算；`AutoAbyssTask` 复用 `BaseCombatTask`，把每座塔封装成“扫描、编队、战斗、结算、返回”的有限状态机。页面识别失败保持保守停止，单塔体力不足和战斗失败继续下一塔。

**Tech Stack:** Python 3.11、OpenCV、NumPy、ok-script、unittest、PowerShell、Git。

**Spec:** `docs/superpowers/specs/2026-09-03-abyss-full-run-design.md`

## Global Constraints

- 只支持中文 PC 客户端与 16:9 的 1920×1080、2560×1440布局。
- 不启动或操控游戏；本次只运行离线测试。
- Python 命令使用 `E:\AI work\ok-wuthering-waves-master\.venv\Scripts\python.exe`。
- 新塔扫描一次体力；同塔继续挑战不重新编队。
- 左右塔体力为 1/2/3/4，中塔每层为 5；三名角色均须覆盖剩余总消耗。
- 发布版本为 `1.28.00`，同步版本、About、更新日志、测试、更新包、提交、注释标签与 GitHub。

---

### Task 1: 完成楼层存在性与纯规划逻辑

**Files:**
- Modify: `src/task/AutoAbyssTask.py`
- Modify: `src/task/abyss_team_planner.py`
- Test: `tests/TestAutoAbyssTask.py`
- Test: `tests/TestAbyssTeamPlanner.py`

**Interfaces:**
- Consumes: 四个固定候选行的完成、锁定和楼层数字证据。
- Produces: `aggregate_floor_states(completed, locked, present)`, `tower_order(priority)`, `tower_required_energy(tower_name, states)`, `plan_team(records, minimum_energy=1)`。

- [ ] **Step 1: 运行新增纯逻辑与楼层扫描测试，确认楼层扫描测试失败。**

  ```powershell
  & .\.venv\Scripts\python.exe -m unittest tests.TestAbyssTeamPlanner tests.TestAutoAbyssTask.TestAutoAbyssTask.test_tower_scan_uses_large_floor_numbers_to_trim_missing_rows -v
  ```

- [ ] **Step 2: 实现大号楼层数字存在性识别并裁掉缺失尾部。**

  `_row_has_floor_number(frame, row, index)` 只在每行左侧数字区域 OCR，精确接受 `str(index + 1)`；`_scan_tower_floors()` 将完成或锁定模板也视作存在证据，并将 `present` 传给 `aggregate_floor_states()`。

- [ ] **Step 3: 重跑定向测试，预期全部通过。**

### Task 2: 将单队编排泛化为按塔与体力门槛编排

**Files:**
- Modify: `src/task/AutoAbyssTask.py`
- Test: `tests/TestAutoAbyssTask.py`

**Interfaces:**
- Produces: `_enter_and_scan_characters(tower_name, states)` 与 `_plan_and_form_team(records, minimum_energy)`。

- [ ] **Step 1: 增加测试，验证塔名决定点击目标且 `minimum_energy` 传入规划器。**
- [ ] **Step 2: 去除残响之塔硬编码，状态文案携带塔名和体力要求。**
- [ ] **Step 3: 运行 `tests.TestAutoAbyssTask` 与 `tests.TestAbyssTeamPlanner`。**

### Task 3: 实现单塔战斗与结算状态机

**Files:**
- Modify: `src/task/AutoAbyssTask.py`
- Test: `tests/TestAutoAbyssTask.py`

**Interfaces:**
- Produces: `_click_start_challenge()`, `_prepare_challenge_map(tower_name, floor_number)`, `_run_floor_combat(tower_name, floor_number)`, `_wait_abyss_result()`, `_fight_selected_tower(tower_name, first_floor_index)`。

- [ ] **Step 1: 运行继续挑战与失败返回测试，确认因 `_fight_selected_tower` 缺失而失败。**
- [ ] **Step 2: 点击编辑队伍页精确的“开启挑战”，等待加载，并在精确识别“环境特性”后按一次 Esc。**
- [ ] **Step 3: 确认队伍世界态，向前寻找“开启挑战”交互，按 F 后调用 `combat_once(target=True)`。**
- [ ] **Step 4: 捕获 `CharDeadException` 后等待结算，不调用传送复活；精确分类结果按钮组合。**
- [ ] **Step 5: “继续挑战”进入下一层；完成或失败点击“返回深塔”；循环上限四层。**
- [ ] **Step 6: 重跑单塔状态机与结果分类测试，预期全部通过。**

### Task 4: 实现三塔调度与结果摘要

**Files:**
- Modify: `src/task/AutoAbyssTask.py`
- Modify: `tests/TestTaskNavigationClassification.py`
- Test: `tests/TestAutoAbyssTask.py`

**Interfaces:**
- Consumes: `self.config[TOWER_PRIORITY]`。
- Produces: 配置下拉、三塔调度、安全返回和最终摘要。

- [ ] **Step 1: 增加 `Tower Priority` 下拉配置，默认 `两侧塔优先`。**
- [ ] **Step 2: 按顺序逐塔扫描；已完成直接跳过，体力不足安全返回，失败跳过余层，其他塔继续。**
- [ ] **Step 3: 结束时输出每塔的完成、失败、已完成跳过或体力不足摘要。**
- [ ] **Step 4: 更新导航分类测试，确认任务仍位于测试功能且已经复用 `BaseCombatTask`。**

### Task 5: 离线回归、版本与发布

**Files:**
- Modify: `config.py`
- Modify: `custom_ok/ok/gui/about/AboutTab.py`
- Modify: `更新日志.md`
- Modify: `tests/TestReleaseReadiness.py`
- Create: `E:\game\okww owener\okww_更新包_20260903.zip`

**Interfaces:**
- Produces: 已验证并发布的 `v1.28.00`。

- [ ] **Step 1: 运行自动深渊、导航、发布一致性和全部离线测试。**
- [ ] **Step 2: 同步 `1.28.00` 与用户可见说明，重跑发布一致性测试。**
- [ ] **Step 3: 用仓库现有打包脚本生成更新包并执行包烟测。**
- [ ] **Step 4: 检查最终 diff，只提交本次文件。**
- [ ] **Step 5: 提交、创建注释标签 `v1.28.00`，推送当前分支与标签。**
