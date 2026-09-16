# 多账号每日任务回归修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复今日证据证明的两处 1.78.00 回归和零分识别缺陷，恢复可验证的每日领取及死亡后恢复流程。

**Architecture:** 保留现有 DailyTask、BaseWWTask 和多账号调度结构。恢复目标积分领取这一缺失阶段，不另建任务系统；通过真实截图与状态变化验证结果。

**Tech Stack:** Python、ok-script、现有 OCR/特征识别、TaskTestCase。

**Spec:** `docs/reviews/2026-09-16-v1.78-daily-regression-diagnosis.md`

## Global Constraints

- 用户已批准执行；实施结果见 `docs/reviews/2026-09-16-daily-regression-implementation.md`。原始任务清单保留用于对照，实机验收尚未执行。
- 使用 `.venv/Scripts/python.exe`；不引入新依赖。
- 不改变备用波片授权、账号身份核验或失败后其他账号继续执行的行为。
- 未知不得伪装成 0 或成功；不增加整账号盲目重试。
- 若修改账号切换，TestAccountSwitchTask 必须复用生产方法；默认精确短名 A1、A3、A4，覆盖备用登录名及掩码手机号。
- 发布版本按实施时最新版本递增补丁位，不覆盖并行工作；更新 config.py 和发行说明，验证后按仓库规范提交、注释标签并推送。NAS 仅使用 192.168.3.173 指定共享路径。
- 上述 superpowers 执行技能若不可用，不冒称已调用；直接按本计划逐项执行即可。

## Task 1：敌迹页正向识别（P0）

Files: 修改 `src/task/BaseWWTask.py`；扩展 `tests/TestDailyFollowupImages.py`；新增脱敏样本 `tests/fixtures/daily_regression/enemy_page.png`。

接口：保留 `_guidebook_content(feature, frame)` 布尔返回，不修改导航调用方。

- [ ] 将 064043_7 的脱敏真实截图纳入固定样本，新增期望正确页面为 True 的测试：

```python
self.set_image('tests/fixtures/daily_regression/enemy_page.png')
self.assertTrue(self.task._guidebook_content('gray_book_all_monsters', self.task.frame))
```

- [ ] 用 ` .\.venv\Scripts\python.exe scripts/run_test_file.py tests/TestDailyFollowupImages.py` 运行，确认旧代码在本断言失败。
- [ ] 将简中匹配至少纠正为实际标题 `敌迹探寻`；其他语言只采用有样本或资源依据的标题，不新增猜测翻译。保持标签与内容联合核验，并测试每日页、加载页不被误认。
- [ ] 重跑同文件及导航相关测试；验证恢复流程已到正确页时不会重开书。将这组改动独立暂存供最终发布提交。

## Task 2：可靠读取真实零分（P0）

Files: 修改 `src/task/DailyTask.py:get_total_daily_points`；扩展 `tests/TestDailyFollowupImages.py`、`tests/TestDailyTaskStatus.py`；增加 `tests/fixtures/daily_regression/unclaimed_zero.png`。

接口：保留现有数值或 None 的返回契约。

- [ ] 从 065016_8 增加真实图片断言，旧实现应失败：

```python
self.set_image('tests/fixtures/daily_regression/unclaimed_zero.png')
self.assertEqual(self.task.get_total_daily_points(), 0)
```

- [ ] 运行上述两个测试文件，记录失败。
- [ ] 优先读取数字专用区域，候选 `.188,.84,.285,.895` 已在本图验证；与页面锚点结合，限制合理数值，保留新帧有限重试和 None。不可用 `value or 0` 消除未知。
- [ ] 增加 0、20、90、100、110、180 数字解析用例，以及加载中、无数字返回 None；对已有不同分辨率真实图片重放，不能只用本图证明通用性。
- [ ] 重跑图片和状态测试，独立暂存本组修改。

## Task 3：恢复“先领积分，再领宝箱”（P0）

Files: 修改 `src/task/DailyTask.py:claim_daily`；扩展 `tests/TestDailyActivityFlow.py`、`tests/TestDailyOutcomeRecovery.py`、`tests/TestDailyFollowupImages.py`。

接口：保留 claim_daily 现有调用契约；目标领取阶段位于已有宝箱扫描之前。

- [ ] 增加 0 分、已完成目标、有黄色领取按钮、无宝箱红点的状态序列测试；不得 mock 掉整个 claim_daily。截图中目标领取识别应非空：

```python
self.set_image('tests/fixtures/daily_regression/unclaimed_zero.png')
buttons = self.task.ocr(.81, .18, .96, .79, match=re.compile('领取'))
self.assertGreaterEqual(len(buttons), 4)
```

- [ ] 状态序列约定：点击目标领取后刷新帧，积分从 0 增长，领取按钮减少；达到 100 后出现宝箱可领态，领取后可领态消失。先确认旧实现在目标点击与最终完成断言失败。
- [ ] 在已确认的每日页面内，只点击目标列表区域的“领取”，不点“前往”；每次点击后重读，避免列表重排时复用旧坐标。限制最多 12 次领取点击、两轮列表滚动；连续两次无状态变化则停止并记录未完成，不死循环。
- [ ] 随后执行现有宝箱领取，刷新积分与可领状态；完成判据不能只是“没有红点”。已做未领奖时不得重打副本或额外兑换波片；仍缺少积分时才恢复现有任务补齐逻辑。
- [ ] 增加重复执行不重复战斗、按钮不响应不会无限点击、奖励弹层关闭后继续、任务行重排、只有前往按钮的测试。运行三个测试文件，独立暂存修改。

## Task 4：原地复苏、恢复链及多账号验收（P0/发布门槛）

Files: 测试 `tests/TestDailyOutcomeRecovery.py`、`tests/TestMultiAccountDailyTask.py`、`tests/TestBaseCombatTask.py`；修改 `src/task/BaseCombatTask.py`、`src/task/DomainTask.py` 的复苏/续战处理，不扩大到角色轮转重构。补充依据为 `docs/reviews/2026-09-16-daily-revive-supplement.md`。

- [ ] 构造“切换死亡角色 → 复苏弹窗 → 点击确认 → 原地续战”，断言不触发退出菜单、重开挑战和额外领奖。当前 CharRevivedException 会被死亡分支捕获退出，测试必须覆盖该继承关系，不能仅断言点击成功。
- [ ] 区分原地恢复、离场恢复、失败；不要直接将既有 CharRevivedException 全局改为原地恢复。检查 NightmareNestTask、FarmEchoTask、WeeklyBossTask 等调用方，保留特殊挑战不自动传送的限制。
- [ ] 只有物品不可用或有限确认无效才走“关闭弹窗 → 退出副本 → 敌迹页 → 治疗 → 返回任务”。页面核验使用真实 fixture；成功复苏也须刷新角色状态，因为物品不恢复满血。
- [ ] 修复基础 revive_action 吞停止类异常的问题：停止、丢帧、进程丢失、配置保护中断原样向上传播。分别验证成功、无物品、冷却、确认无响应、重复阵亡与中途停止。
- [ ] 将任务积分领取放在初始/补跑/补齐授权的读取阶段，不只在 ready=None 时领取；用“领取后已达100但消耗目标未满”案例断言不为凑活跃度额外兑换备用波片。保留用户明确配置的现有体力清理、完整聚落任务。
- [ ] 验证 A3 恢复失败不阻断 A4，A4 已做未领奖优先领奖；保留账号级现有重试上限和断点隔离。
- [ ] 运行定向测试和完整测试集，报告失败及跳过，不仅给通过数量。
- [ ] 经用户授权运行实机 A1/A3/A4，分别覆盖新一天、已有进度未领奖、已完成；核实账号身份、积分、宝箱状态、是否多耗波片和最终结果。记录实际版本和截图；缺少实机条件时明确只完成离线验证。
- [ ] 同步版本与发行说明，审查仅包含本计划文件的 diff；按版本规范提交、创建匹配注释标签并推送。发布后再用新日志确认，不能以旧日志宣布修复完成。

## 不采用的方案

不整体回退到很早版本；不增加账号重试次数解决确定性条件错误；不把所有 OCR 失败当 0；不因零散解放警告同时重写战斗和输入系统。当前有证据的最小修复范围是页面、积分识别和领取顺序。
