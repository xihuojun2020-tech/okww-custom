# 每账号创建刷取任务实施计划

**Goal:** 将固定材料槽位改为每账号独立任务列表，保留现有战斗、领奖核验、体力预算和账号身份核验。

**Architecture:** 任务配置保存稳定 ID、类型、名称、启用状态及现有目标参数。调度按模块优先级、组内列表顺序执行；突破和周本以独立领取账本计数，凝素沿用 goal_id 流水。迁移任务引用原进度，新建任务从零开始。

**Tech Stack:** Python、PySide6、现有 Fluent 控件与 SectionPanel、ConfigIntegrityService。

**Spec:** 本会话已确认需求：周本→每日聚落→全部突破→全部凝素→无限保底→活跃度领取；周本每周三次、周一执行周日复核；有限目标跨日跨周保存；突破及周本输入领取次数；凝素输入已有和所需四品质数量。每次开始及账号切换核验特征码。统一现有 UI，不增加启动确认。

## 实施步骤

- [x] `src/task/farming_task_queue.py`：任务配置校验、旧配置幂等迁移、单任务配置投影、独立账本、完成状态；覆盖重复关卡独立累计、旧凝素不限和旧领取进度。
- [x] `src/account_task_policy.py`、`src/config_integrity.py`、`src/account_repository.py`：启动与导入迁移、新账号模板复制新 ID、配置完整性验证。
- [x] `WorldBossMaterialTask`、`WeeklyBossTask`：允许队列注入单项进度；有限周本结束后停止，不自动刷未创建的首项保底。
- [x] `DailyTask`：调用现有生产执行入口、复用体力预算，组内完成后转下一项；周额度用完保留未完成目标。
- [x] `FarmingTaskQueueWidget`、`AccountConfigTab`：统一刷取任务入口、添加与编辑弹窗、暂停/恢复、组内上下移、完成归档、领取核对；同步新账号模板。
- [x] `account_task_state.py`：每实例总览、完成时间、周检查时间与每日无限任务重置。
- [x] 用仓库 `.venv` 执行针对队列、迁移和每日/周本/账号界面的有效检查；生成实际 Qt 页面图检查统一性。
- [x] 审查 diff，升级 patch 版本及发行说明，验证、提交、标记并推送；更新本机打包版和 NAS 更新包，核对身份、序列、自动战斗偏好与迁移结果。

## 验证命令

```powershell
.\.venv\Scripts\python.exe scripts/run_test_file.py tests/TestFarmingTaskQueue.py --timeout 60
.\.venv\Scripts\python.exe scripts/run_test_file.py tests/TestFarmingTaskQueueUI.py --timeout 60
.\.venv\Scripts\python.exe scripts/run_test_file.py tests/TestAccountTaskOverview.py --timeout 60
```

游戏消耗体力的实际挑战不作为无条件自动测试；自动检查与实际运行结果分别报告。

## 验收结果

1.97.35 已推送 GitHub，NAS stable 与本机打包版同步更新。504 项自动检查通过；实际 Qt 渲染已检查。升级后10个账号迁移为21项刷取任务，身份、槽位、旧意图、领取进度、完成时间及自动战斗偏好核对通过，486个来源文件哈希一致，启动没有 ERROR。没有进行实际消耗体力的游戏挑战。
