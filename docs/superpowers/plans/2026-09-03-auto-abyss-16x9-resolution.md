# 自动深渊 16:9 分辨率兼容 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让自动深渊在 720P 至 4K 的任意标准 16:9 捕获分辨率下使用同一套比例识别与点击逻辑。

**Architecture:** 保留现有归一化区域和按帧高缩放的模板匹配，只新增任务入口分辨率门禁及统一局部 OCR 缩放函数。所有分辨率行为通过纯函数和合成帧离线测试验证，不新增依赖或分辨率配置表。

**Tech Stack:** Python 3.11、OpenCV、NumPy、ok-script、unittest、PowerShell、Git。

**Spec:** `docs/superpowers/specs/2026-09-03-auto-abyss-16x9-resolution-design.md`

## Global Constraints

- 支持范围为不低于 1280×720 的标准 16:9 捕获帧。
- 非 16:9 或低于 720P 必须在第一个游戏操作前停止。
- 不缩放整帧、不维护多套坐标、不新增依赖。
- 只运行离线测试，不启动或操控游戏。
- 发布版本为 `1.28.01`。

---

### Task 1: 添加分辨率门禁

**Files:**
- Modify: `src/task/AutoAbyssTask.py`
- Test: `tests/TestAutoAbyssTask.py`

**Interfaces:**
- Produces: `validate_abyss_resolution(frame, minimum=(1280, 720), tolerance=0.02) -> tuple[int, int]`。

- [ ] **Step 1: 写失败测试，覆盖五种支持分辨率、非 16:9、低于 720P 和空帧。**
- [ ] **Step 2: 实现纯校验函数；错误消息包含实际宽高和要求。**
- [ ] **Step 3: 在 `run()` 的 `openF2Book()` 之前调用校验、记录捕获分辨率，失败时沿用任务错误状态。**
- [ ] **Step 4: 运行 `tests.TestAutoAbyssTask`，预期通过。**

### Task 2: 统一角色模板与局部 OCR 缩放

**Files:**
- Modify: `src/task/AutoAbyssTask.py`
- Test: `tests/TestAutoAbyssTask.py`

**Interfaces:**
- Produces: `ocr_resize_scale(image_height, target_height, maximum=4.0) -> float`。

- [ ] **Step 1: 写失败测试，确认 720P 需要放大、1080P/1440P适度放大、4K不超过目标尺寸。**
- [ ] **Step 2: 将 `_read_slot_number()`、`_read_slot_energy()` 和 `_read_selection_number()` 的固定倍数替换为统一缩放函数。**
- [ ] **Step 3: 将角色模板目标高度改为 `max(64, round(self.height * 0.105))`。**
- [ ] **Step 4: 扩展角色卡和选择编号合成测试到五种分辨率并运行。**

### Task 3: 发布 1.28.01

**Files:**
- Modify: `config.py`
- Modify: `custom_ok/ok/gui/about/AboutTab.py`
- Modify: `更新日志.md`
- Modify: `tests/TestReleaseReadiness.py`

**Interfaces:**
- Produces: 更新包 `E:\game\okww owener\okww_更新包_20260903.zip` 与标签 `v1.28.01`。

- [ ] **Step 1: 运行自动深渊、导航、发布一致性和完整单元测试组。**
- [ ] **Step 2: 同步版本与用户可见说明并运行发布校验。**
- [ ] **Step 3: 重新生成更新包，验证包内版本、边界和 SHA-256。**
- [ ] **Step 4: 检查最终差异，提交、创建注释标签并推送分支和标签。**
