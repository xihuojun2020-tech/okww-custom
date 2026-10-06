# 固定账号位置重新编号 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 首次按实际序列顺序映射 A1～A10、B1～B10，后续账号资料和台账按 UUID 保留，位置编号可重新绑定。

**Architecture:** 在已有 account_slots 中增加一次性的 v2 迁移标记，固定序列列表是首次绑定的唯一来源。保留历史存储名称作为兼容键，显示及精确编号解析使用固定槽位；身份验证仍使用手机号、备用登录名和特征码。

**Tech Stack:** Python 3.12、PySide6、现有账号发布事务。

**Spec:** 用户 2026-10-06 确认按实际序列顺序自动重新编号；原 B10 位于第一序列第九位时显示 A9。

## Global Constraints

- UUID、手机号、昵称、特征码、任务设置、完成记录不因重新编号变化。
- 已确认 v2 的槽位后续不压缩，不在每次启动时重新编号。
- 旧配置导入也执行相同迁移；跨序列重复和超过十个成员保留原名单并提示核对。
- 使用本地 .venv；NAS 仅 .173；版本 1.97.21，验证后提交和发布主工作区、打包版、NAS。
- 在当前会话内执行，保留无关文档修改；不运行真实游戏任务。

### Task 1: 迁移和固定编号解析

**Files:** src/account_slots.py、src/account_identity.py、src/account_display.py、src/account_config_bundle.py；tests/TestAccountSlots.py、tests/TestAccountIdentity.py。

**Interfaces:** 保持 migrate_slots(raw) -> (candidate, changed)、account_slot(account)、resolve_profile_short_names(names, profiles) 的调用方式。

- [x] 用 B10、B17、B18 历史名称构造两个序列，断言实际列表顺序产生 A/B 新编号，UUID 和 task_config 不变。
- [x] 迁移一次后使用 extensions.fixed_account_slots_v2 阻止重复编号；未分配账号不再根据旧名称占位。
- [x] account_display_label 使用固定槽位；resolve_profile_short_names 按新槽位选择 UUID，旧存储名称继续用于已保存的账号引用。
- [x] 在配置包完成身份/序列解析后调用 migrate_slots，保留完成台账。
- [x] 运行 `.venv/Scripts/python.exe -m unittest tests.TestAccountSlots tests.TestAccountIdentity tests.TestAccountConfigBundle tests.TestSequenceRepository`。

### Task 2: 验证与发布

**Files:** config.py、README.md、更新日志.md、必要账号 UI 回归与检查报告。

- [x] 验证迁移、跨序列移动、位置占用拒绝、配置包往返、切号测试和 UI 账号标签。
- [x] 打包和执行生产安装器验证；正常关闭打包版，备份后升级并检查账号图符合 migrate_slots、运行台账和战斗偏好完整保留。
- [x] 发布 NAS 更新包并回读清单与 SHA-256；提交明确文件，创建 v1.97.21 并推送，同步打包版仓库记录。
