# 运行时稳定性与发布恢复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 恢复可安装 Release，并让游戏崩溃、梦魇巢穴短暂脱战误判和领域进入超时得到有界、可诊断且不会误领奖的处理。

**Architecture:** 分两次发布。`1.41.08` 仅修复安装器源码校验器对 PowerShell CRLF 的误报，使已经完成的诊断上传修复可交付；`1.42.00` 再在公共截图边界、梦魇巢穴任务边界和领域入口边界分别增加最小保护。游戏自身 `Fatal error!` 只识别为窗口/截图失效并停止或执行已有的一次受控重启，不尝试由脚本修复游戏进程。

**Tech Stack:** Python 3.12、unittest、OpenCV、Pillow、PowerShell、GitHub Actions、7-Zip/NSIS。

**Spec:** `docs/NAS诊断部署与读取说明.md` 的“2026-09-08 另一台设备检查记录”和“1.41.06 发布状态”。

## Global Constraints

- Python 命令必须使用 `./.venv/Scripts/python.exe`。
- 每次代码发布必须同步 `config.py`、`更新日志.md` 和产品可见版本文字。
- 固定宽度版本：发布恢复为 `1.41.08`（`1.41.07` 已存在）；运行时中等变更为 `1.42.00`。
- 不移动或覆盖 `v1.41.03` 至 `v1.41.06` 的失败标签。
- 不纳入工作区现有 `docs/reviews/` 删除。
- `GameProcessLost`、`FrameUnavailable`、用户停止、配置完整性错误和角色死亡必须原样传播，不得转成普通战斗结束或领奖信号。
- 未获得明确战后证据时不领奖、不扣体力、不标记任务完成。

---

### Task 1: 修复 PowerShell 源码换行误报并发布 1.41.08

**Files:**
- Modify: `scripts/inspect_installer.py`
- Modify: `tests/TestPackageSmoke.py`
- Modify: `config.py`
- Modify: `更新日志.md`

**Interfaces:**
- Consumes: `inspect_extracted(payload: Path, reference: dict[str, bytes], version: str) -> dict`
- Produces: `.ps1` 仅 CRLF/LF 不同可进入 `eol_only_differences`；任何其他字节变化继续抛出 `ValueError`

- [x] **Step 1: 写入 PowerShell 换行回归测试**

在 `TestPackageSmoke` 中构造 `src/runtime/install_diagnostic_task.ps1`：引用内容使用 LF，`repo` 与 `working` 使用 CRLF。断言 `inspect_extracted()` 成功，并断言两个源码树的 `eol_only_differences` 都包含该路径。

```python
reference = {
    'config.py': b'version = "1.41.08"\n',
    'src/runtime/install_diagnostic_task.ps1': b"Write-Output 'ok'\n",
}
result = inspect_extracted(root, reference, '1.41.08')
self.assertTrue(all(
    'src/runtime/install_diagnostic_task.ps1' in tree['eol_only_differences']
    for tree in result['source_trees']
))
```

- [x] **Step 2: 验证测试在当前代码失败**

Run: `./.venv/Scripts/python.exe -m unittest tests.TestPackageSmoke.TestPackageSmoke.test_powershell_eol_only_difference_is_allowed -v`

Expected: FAIL，错误为“安装器源码与引用版本不一致：src/runtime/install_diagnostic_task.ps1”。

- [x] **Step 3: 最小修改文本后缀集合**

在现有 EOL 白名单中加入 `.ps1`，不放宽二进制文件、路径检查、缺文件检查或内容比较。

```python
EOL_NORMALIZED_SUFFIXES = {
    '.py', '.txt', '.md', '.in', '.yml', '.po', '.bat', '.ps1',
    '.json', '.svg', '.qss',
}
```

- [x] **Step 4: 增加非换行差异拒绝测试**

将安装器内 `.ps1` 内容改成 `Write-Output 'changed'`，断言仍抛出“源码与引用版本不一致”。

- [x] **Step 5: 更新 1.41.08 版本与发布说明**

`config.py` 改为 `1.41.08`；更新日志说明 `1.41.06` 与 `1.41.07` 没有 Release、实际失败原因是 `.ps1` CRLF 误报，且校验安全边界没有放宽。

- [x] **Step 6: 执行发布链路聚焦验证**

Run:

```powershell
./.venv/Scripts/python.exe -m unittest tests.TestPackageSmoke tests.TestReleaseReadiness -v
./.venv/Scripts/python.exe ./scripts/validate_release.py --tag v1.41.08
git diff --check
```

Expected: 全部 PASS，版本输出 `1.41.08`。

- [ ] **Step 7: 提交和发布 1.41.08**（提交、标签和推送已完成；Actions 安装器构建与 Release 核验仍在进行）

仅暂存 Task 1 文件，提交 `fix: accept PowerShell checkout line endings`，创建 annotated tag `v1.41.08`，推送分支和标签。等待流水线全部通过，并确认 Release 同时包含离线/在线安装器、`okww_update_v1.41.08.zip`、`RELEASE_NOTES.md`、安装器 manifest 和 `SHA256SUMS.txt`。

---

### Task 2: 在公共颜色检测入口统一拦截空帧

**Files:**
- Modify: `src/task/BaseWWTask.py`
- Modify: `src/combat/CombatCheck.py`
- Modify: `tests/TestGameRuntimeErrors.py`
- Modify: `tests/TestCombatCheck.py`

**Interfaces:**
- Consumes: `BaseWWTask.require_game_frame() -> numpy.ndarray`
- Produces: `BaseWWTask.calculate_color_percentage(color, box) -> float` 在取色前固定一帧；窗口丢失抛 `GameProcessLost`，窗口存在但无帧抛 `FrameUnavailable`

- [x] **Step 1: 写公共颜色检测空帧测试**

覆盖三种状态：有效帧正常计算；窗口存在但帧为 `None` 抛 `FrameUnavailable`；窗口不存在抛 `GameProcessLost`。断言底层颜色函数在两个错误分支均未调用。

- [x] **Step 2: 验证当前实现复现 `NoneType.shape`**

Run: `./.venv/Scripts/python.exe -m unittest tests.TestGameRuntimeErrors.TestGameRuntimeErrors.test_color_percentage_classifies_missing_frame -v`

Expected: FAIL，当前基类路径进入底层 `image.shape`。

- [x] **Step 3: 覆盖颜色检测并使用同一帧快照**

在 `BaseWWTask` 中调用 `require_game_frame()`，解析 box 后把该局部帧传给底层 `ok.util.color.calculate_color_percentage`，保留 `box.confidence` 与 `draw_boxes()` 行为。

```python
def calculate_color_percentage(self, color, box):
    frame = self.require_game_frame()
    box = self.get_box_by_name(box)
    percentage = calculate_frame_color_percentage(frame, color, box)
    box.confidence = percentage
    self.draw_boxes(box.name, box)
    return percentage
```

- [x] **Step 4: 固定 CombatCheck 直接读取的帧**

`has_health_bar()` 开头获取 `frame = self.require_game_frame()`，本次检测内所有 `find_color_rectangles()`、`crop_frame()` 使用同一局部帧，避免一次判断内帧从有效变为 `None`。

- [x] **Step 5: 验证异常传播边界**

确认 `CombatCheck.in_combat()`、`BaseCombatTask.combat_once()`、`DailyTask` 和 `MultiAccountDailyTask` 不会把 `GameProcessLost`/`FrameUnavailable` 转成 `NotInCombatException`、`CombatStateUnknown` 或战斗完成。已有 `_restart_game_once()` 仍最多调用一次。

- [x] **Step 6: 运行公共帧与战斗检查测试**

Run: `./.venv/Scripts/python.exe -m unittest tests.TestGameRuntimeErrors tests.TestCombatCheck tests.TestBaseCombatTask -v`

Expected: 全部 PASS；不再出现 `NoneType.shape`。

---

### Task 3: 梦魇巢穴对战中脱战做任务级有限复核

**Files:**
- Modify: `src/task/NightmareNestTask.py`
- Modify: `tests/TestNightmareNestTask.py`

**Interfaces:**
- Consumes: `CombatStateUnknown`、`NestTarget.current/total`、`has_target()`、`check_health_bar()`、OCR 的 `current/total` 文本
- Produces: `_recheck_nest_combat(nest: NestTarget, timeout: float = 8) -> str`，返回 `combat`、`complete` 或 `unknown`

- [x] **Step 1: 写三态复核测试**

覆盖：新帧重新出现目标返回 `combat`；左侧目标计数仍小于总数返回 `combat` 并执行一次重新锁敌；计数达到总数返回 `complete`；空白/OCR 陌生且无目标返回 `unknown`；`FrameUnavailable` 和用户停止原样抛出。

- [x] **Step 2: 写有限恢复次数测试**

让第一次 `combat_once()` 抛 `CombatStateUnknown`，复核返回 `combat`，断言仅重进同一场战斗一次；第二次仍未知必须抛出原异常，不得无限循环，不得重新点击挑战入口。

- [x] **Step 3: 实现梦魇专用复核**

最多等待 8 秒并读取新帧。优先级为：目标框/敌人血条 → `combat`；左侧同一总数的 `current < total` → `combat`；明确 `current == total` → `complete`；其余 → `unknown`。战斗文案或计数为空不能作为完成依据。

- [x] **Step 4: 接入 combat_nest**

只捕获 `CombatStateUnknown`。`combat` 时重新锁敌并继续一次；`complete` 时进入原有拾取流程；`unknown` 保存 `nightmare_combat_unknown` 截图后重抛。不得捕获 `CharDeadException`、`FrameUnavailable`、`GameProcessLost` 或 `TaskDisabledException`。

- [x] **Step 5: 验证截图中的回归场景**

构造“左侧 35/41、敌人仍存在、公共战斗检测暂时返回 false”的测试，断言不会标记梦魇巢穴完成，也不会返回每日任务页面。

- [x] **Step 6: 运行梦魇与每日任务测试**

Run: `./.venv/Scripts/python.exe -m unittest tests.TestNightmareNestTask tests.TestDailyActivityFlow -v`

Expected: 全部 PASS。

---

### Task 4: 领域进入超时增加一次安全恢复和现场证据

**Files:**
- Modify: `src/task/DomainTask.py`
- Modify: `tests/TestDomainRecoveryLoop.py`

**Interfaces:**
- Consumes: `teleport_into_domain_once: Callable[[], None]`、`WaitFailedException`、`require_game_frame()`、`ensure_main()`
- Produces: `farm_domain_with_recovery_loop(..., max_entry_retries: int = 1)`，只在进入领域且尚未战斗/扣体力前允许一次恢复重试

- [x] **Step 1: 写进入超时恢复测试**

第一次回调抛 `WaitFailedException`、第二次成功时，断言执行一次 `ensure_main(time_out=120)` 后重开 F2 流程；`farm_in_domain()` 只在成功进入后调用。

- [x] **Step 2: 写失败边界测试**

连续两次进入超时应保存 `domain_entry_unknown` 截图并抛 `CombatStateUnknown`；断言不调用 `use_stamina()`。`FrameUnavailable`、`GameProcessLost` 和用户停止不重试且原样传播。

- [x] **Step 3: 在外层入口循环实现独立预算**

进入重试与死亡恢复重试使用不同计数器。只捕获 `WaitFailedException`；先调用 `require_game_frame()` 区分游戏崩溃，再记录当前是否在队伍、是否仍有挑战/确认按钮，保存现场截图。第一次执行 `ensure_main(time_out=120)` 后重试，第二次转为带上下文的 `CombatStateUnknown`。

- [x] **Step 4: 保持奖励安全边界**

确认进入超时路径不会调用 `_finish_domain_combat()`、`walk_to_treasure()`、`has_claim_stamina()` 或 `use_stamina()`；现有“未知不领奖”测试继续通过。

- [x] **Step 5: 运行领域、凝素和模拟领域测试**

Run: `./.venv/Scripts/python.exe -m unittest tests.TestDomainRecoveryLoop tests.TestForgeryDomainLabels -v`

Expected: 全部 PASS。

---

### Task 5: 保持 Mornye 单次大招异常为观测项

**Files:**
- Verify only: `src/char/BaseChar.py`
- Verify only: `src/char/Mornye.py`
- Verify only: `tests/TestChar.py`

**Interfaces:**
- Consumes: `_log_liberation_unconfirmed(started, send_attempts)` 现有遥测
- Produces: 不新增自动重按；保留 `send_attempts`、`frame_age`、窗口存在/可见和输入投递状态

- [x] **Step 1: 确认现有日志字段完整**

验证单次记录已经包含角色名、原因、发送次数、确认超时、耗时、帧年龄、窗口状态和 `input_delivery=unverified`。

- [x] **Step 2: 不修改战斗行为**

本轮不增加第二次 R 输入。只有新版本实机日志中同角色、同状态连续出现至少 3 次，且窗口与帧均健康时，才另立任务评估一次受控重按。

---

### Task 6: 集成验证并发布 1.42.00

**Files:**
- Modify: `config.py`
- Modify: `更新日志.md`
- Modify: `docs/NAS诊断部署与读取说明.md`
- Test: Tasks 2–4 列出的测试文件

**Interfaces:**
- Consumes: Tasks 2–4 的运行时错误分类和有界恢复行为
- Produces: 可安装的 `v1.42.00`，升级说明要求完整重启以重建诊断运行环境

- [x] **Step 1: 更新版本与说明**

将 `config.py` 更新为 `1.42.00`；更新日志逐项说明空帧分类、梦魇有限复核、领域入口一次恢复及未修改的 Mornye 边界。

- [x] **Step 2: 运行聚焦测试组**

Run:

```powershell
./.venv/Scripts/python.exe -m unittest tests.TestGameRuntimeErrors tests.TestCombatCheck tests.TestBaseCombatTask tests.TestNightmareNestTask tests.TestDomainRecoveryLoop -v
```

Expected: 全部 PASS。

- [x] **Step 3: 运行仓库完整测试和发布校验**

使用 `.github/workflows/build.yml` 中与 CI 相同的 unittest 模块集合运行，不降低超时、不跳过已有样本测试。随后运行：

```powershell
./.venv/Scripts/python.exe ./scripts/validate_release.py --tag v1.42.00
git diff --check
```

- [x] **Step 4: 检查提交范围**

`git diff --cached` 只能包含 Tasks 2–6 的文件以及先前明确要求更新但尚未提交的 NAS 诊断文档，不包含 `docs/reviews/` 删除或其他用户修改。

- [ ] **Step 5: 发布并核验真实 Release**

提交 `fix: harden combat recovery after capture loss`，创建 annotated tag `v1.42.00` 并推送。等待 `validate-version`、`tests`、`package`、`artifact-content-check`、`checksums`、`github-release` 全部成功；最后从 Release 页面核对安装器、源码更新 ZIP 与 SHA-256 清单真实可下载。

- [ ] **Step 6: 另一台设备实机验收**

升级后完整退出并重启程序。分别验证：游戏手动关闭时报告窗口丢失而非 `NoneType.shape`；梦魇巢穴短暂丢目标后继续当前战斗且不提前完成；领域进入卡住时最多恢复一次且不扣体力；NAS 中新日志不再出现旧异常类型。

## 明确不在本计划内

- 不修改显卡驱动、游戏文件或 Windows 设置来“修复”鸣潮 `Fatal error!`。
- 不为 Mornye 单次未确认增加盲目重复输入。
- 不把任何空帧、未知 OCR、窗口丢失或加载超时解释为胜利、领奖或任务完成。
