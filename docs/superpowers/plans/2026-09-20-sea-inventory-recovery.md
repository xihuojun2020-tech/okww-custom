# Sea Inventory and Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. 当前会话未提供这些执行技能；按用户授权在本会话内逐项实施及验证，不派发子代理。

**Goal:** 去掉海墟重复点击全部信物，并支持人工接管后重试未完成阶段。

**Architecture:** 静态目录与纯评分负责规则，视觉模块负责列表卡片，独立恢复mixin管理本进程阶段。任务类复用既有扫描、战斗、寻路和框架暂停接口，不改公共任务。

**Tech Stack:** Python、dataclasses、OpenCV、现有OCR、ok-script、unittest。

**Spec:** `docs/superpowers/specs/2026-09-20-sea-inventory-recovery.md`

## Global Constraints

- 使用本地虚拟环境；在独立工作树修改，原工作区用户改动不纳入。
- 只使用 `\\192.168.3.173\羲火君 共享给我\AI诊断` 发布NAS更新。
- 不改变已验证的出口寻路；不自动进行实机游戏测试。
- 版本1.81.00，与更新日志及用户文档同步；回归通过后提交和发布匹配标签。

## Task 1: Static catalogue and no-click inventory

Files: `src/task/sea_ruins_tokens.py`, `src/task/sea_ruins.py`, `src/task/sea_ruins_vision.py`, `src/task/AutoSeaRuinsTask.py`, `tests/TestSeaRuinsImages.py`, `tests/TestSeaRuinsRecovery.py`。

Interfaces: `identify_token(caption, rarity=None) -> TokenRule | None`；`_page_tokens(frame) -> list[(Token, rect)]`；`_inventory_page()`三次有界重读；原`choose_loadout`继续消费Token。

- [x] 收集当前3金/6紫/3蓝规则，逐条记录来源；保留模态不明时的保守评分。
- [x] 编写并运行截图测试，断言7个未锁定信物的数量为 `[2, 1, 2, 2, -1, -1, -1]` 且 `click_relative.assert_not_called()`。
- [x] 实现名称唯一前缀匹配、卡片颜色分类、仅目标携带与完整名称确认。1080p回归发现边框漏检后补品质色条定位，三分辨率通过。
- [x] 添加蓝色普攻/重击队适配、有限次数和未知项安全测试。

## Task 2: Known popup and checkpoints

Files: `src/task/sea_ruins_recovery.py`, `src/task/AutoSeaRuinsTask.py`, `src/task/sea_ruins_vision.py`, `tests/TestSeaRuinsRecovery.py`, `tests/fixtures/sea_ruins/unlock.png`, `assets/images/sea_ruins/sea_world.png`。

Interfaces: `_sea_step() -> next_stage`只在动作确认后推进；`_resume_sea_stage() -> stage`只在画面与身份核对后重定位；`_pause_for_sea_error(error)`释放输入并阻塞在原暂停接口。

- [x] 把现有顺序流程拆为进入、扫描、计划、上下队与信物、进场、上下战斗、出口、结算、下一层检查点。
- [x] 使用真实解锁截图编写双文案识别；至多3次空白区域关闭，非目标弹窗不点击。
- [x] 先释放输入再暂停，暂停期间睡眠回调为-1；恢复重置画面缓存和战斗计时，用户停止不捕获为恢复错误。
- [x] 模拟验证 `fight_upper -> enter_lower`，人工下半 `-> start_lower`，返回详情 `-> presets`，未知页面再次暂停。
- [x] 模拟5层循环，断言预设/库存各扫描5次、携带10次、出口5次、下一层4次；不会重复处理成功槽位。

## Task 3: Regression, documentation and release

- [x] 使用 `scripts/run_test_file.py` 每套单独进程运行海墟规则、流程、真实OCR、恢复、周本任务/截图、每日领取和多账号测试；读取结果JSON，不以PowerShell最后命令状态替代测试结果。
- [x] 更新信物资料、使用文档、检查点限制、版本配置和更新日志。
- [ ] 打包并以v1.80.04为基线核验，检查staged diff仅含此功能。
- [ ] 提交、创建v1.81.00注解标签并推送；发布NAS后回读版本和SHA256。
- [ ] 向用户交付更新及手动验收提示，不宣称实机通过。
