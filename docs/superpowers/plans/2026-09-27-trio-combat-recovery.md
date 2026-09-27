# 三人队战斗恢复实施计划

**Goal:** 修复两天日志中跨账号旧角色脚本、双辅助循环和清宵空转，并保存无异常抛出时的战斗证据。

**Architecture:** 由每日账号绑定发布共享缓存代次，所有战斗子任务在读取队伍及执行动作前校验。轻量轮转状态只记录已执行准备和确认切换，在正常动作结束的切人节点恢复主输出；角色超时先复核身份。

**Tech Stack:** 现有 Python、ok-script、unittest、诊断截图及事件采集。

**Spec:** `docs/reviews/2026-09-27-nas-two-day-trio-combat-analysis.md` 第 7 节；用户已批准执行。

## 约束

- 在当前隔离工作区实施，保留所有原有未跟踪文件。
- 使用主仓库 `.venv/Scripts/python.exe`，不新增依赖。
- 只访问 `\\192.168.3.173\羲火君 共享给我\AI诊断`。
- 不伪造增益、协奏或技能成功，不打断原有技能动作与切换锁定。
- 异常证据复用现有 `okww监控室` 保存链路，按原因限频。
- 离线验证后同步版本、README、更新日志，提交并推送匹配注释标签；实机验证状态据实报告。

## 执行步骤

- [x] 账号上下文：`src/combat/roster_context.py` 发布缓存代次；`DailyTask.bind_verified_profile` 调用；`BaseCombatTask.load_chars` 与 `CharFactory` 共享上下文。在角色动作入口检测代次变化。测试相同窗口 B7→B8→B10、重复登录同账号、单账号与多账号共用子任务。
- [x] 轮转恢复：`src/combat/rotation_state.py` 记录准备过的辅助、确认切入次数及驻场时间。在 `_choose_switch_target` 中辅助均尝试后选择可用且不受锁定的主输出。测试正常增益、无增益、MUST 优先级、冷却和失败切换。
- [x] 超时复查：穗穗超时暂停当前轮转，下一动作前全量比对角色。身份未变时保留失败冷却与协奏状态，失败期间缩短再次等待并降低重试优先级；不同身份确认后切换脚本。消除 `try_e` 路径一次轮转发起两次换人的问题。
- [x] 清宵降级：复用现有单人可用技能判断，在三人前置不完整时执行有限基础输出，再换人。验证有/无增益、有/无变奏、技能冷却、正常完整输出和既有单人行为。
- [x] 留证和统计：轮转异常日志、按原因限频截图、诊断事件与录像时间关联；每场输出脚本身份、切入/驻场、准备结果、技能尝试/观察结果、超时与降级次数。证据失败不能改变任务结果，停止指令必须继续传播。
- [x] 验证与发布准备：新回归测试、既有角色身份/轮转/每日/账号测试及截图识别检查已通过，差异与版本元数据已核对。按本会话收尾命令提交、创建标签、推送并核实远端；验证明细见 `docs/reviews/2026-09-27-trio-combat-fix-verification.md`。

## 回归的最低断言

```python
# 每个辅助已尝试，但增益均未建立：主输出得到机会。
assert task._choose_switch_target(iuno, has_intro=False) is qingxiao
# 主输出仍受切换锁定时不可强行选取。
assert task._choose_switch_target(iuno, has_intro=False) is not locked_main
# 新账号代次使旧头像对象失效，首次动作前已换成正确脚本。
assert child.prepare_character_rotation(old_char) is False
assert child.chars[1].name == 'Denia'
```

按本会话顺序实施并自审；不再申请一次已经获得的方案批准。
