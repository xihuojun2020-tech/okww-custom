# Completion Evidence Implementation Plan

**Goal:** 在当前任务实现账号完成证据看板、手动留证及可靠结果点自动采集。

**Architecture:** SQLite 和独立原图组成永久本地证据仓库；服务冻结账号上下文并串行后台保存；Qt 页面只读展示，人工采集经执行器边界完成。自动适配器不得写生产进度。

**Tech Stack:** Python 标准库、SQLite、OpenCV、PySide6、QFluentWidgets。

**Spec:** `docs/superpowers/specs/2026-09-10-completion-evidence-design.md`

用户已要求直接在当前任务实施，按步骤内联执行；当前可用技能不含 executing-plans，不另派子任务。

## Global Constraints

- 所有已保存证据截图长期留存，只有用户明确手动删除才可移除。
- 不自动上传、不覆盖原图，不以容量不足为由删旧图。
- 手动确认只影响看板；不修改 DailyTask/MultiAccountDailyTask 完成记录。
- UUID 在采集时固定；新证据不依赖 NAS；只测试合成账号和图片。
- Python 使用 `.venv/Scripts/python.exe`。已有 reviews 删除及其他需求文档不纳入提交。
- 代码交付同步固定宽度版本、日志、文档；通过验证再提交并推送标签。

## 1. 仓库与周期

文件：新增 `src/evidence/model.py`、`src/evidence/repository.py`、`tests/TestCompletionEvidence.py`。

接口：`period_for(project_id, when)` 返回游戏日/游戏周或 None；`EvidenceRepository(root).save(metadata, frame)` 返回记录；`list_records(profile_id, project_id=None, trashed=False, limit=100, offset=0)` 分页；`trash(evidence_id)`、`restore(evidence_id)` 仅由显式 UI 操作调用，不提供定时清理。

- [x] 写仓库测试，覆盖 UUID、周期、原图保留、回收恢复、路径和缺图。
- [x] 运行 `python -m unittest tests.TestCompletionEvidence` 确认新增接口缺失时失败。
- [x] 实现独立 PNG、缩略图、SQLite 元数据，文件先原子落盘后提交索引；图片缺失时返回 missing；永久删除需单独显式确认标记。
- [x] 复跑测试，包括失败路径中原图仍存在。

```python
when = datetime.fromisoformat('2026-09-14T03:59:00+08:00')
assert period_for('daily_activity', when) == 'day:2026-09-13'
assert period_for('weekly_boss', when) == 'week:2026-09-07'
```

## 2. 后台服务与截图边界

文件：新增 `src/evidence/service.py`，修改 `custom_ok/ok/task/TaskExecutor.py`。

接口：`submit(metadata, frame)` 冻结数据并返回 Future；`request_capture(executor)` 返回等待新画面的 Future；`process_capture(executor)` 仅在执行器检查点采集。请求带超时与绑定快照，无 UI 并发截图。

- [x] 写暂停状态采集、不发送输入、超时取消、后台变更账号不串号测试。
- [x] 实现有界队列和串行工作线程，窗口/帧/绑定检查后复制画面；取消或过期请求不采集、不保存。
- [x] `check_enabled` 只在已存在 capture 请求时调用处理，不改变正常任务暂停/停止行为；空闲 next_task 也处理请求。
- [x] 测试人工保存服务不调用生产完成记录接口。

```python
metadata = {'profile_id': account_uuid, 'project_id': 'daily_activity', 'source': 'manual_capture'}
future = service.submit(metadata, frame)
metadata['profile_id'] = other_uuid
assert future.result()['profile_id'] == account_uuid
```

## 3. 六页导航和手动证据 UI

文件：新增 `src/gui/CompletionCheckTab.py`，修改 navigation_sections、MainWindow、TaskCard，新增 `tests/TestCompletionCheckUI.py`。

接口：`CompletionCheckTab(executor, repository=None)`；`capture_evidence(project_id=None)`；公共任务菜单使用页面接口，不独立实现截图。

- [x] 测试只读选择、六页导航、人工确认来源及缺图；账号顺序复用投影。
- [x] 实现账号搜索/序列、当前周期/历史、待核验筛选、响应式网格及详情，保留原图比例。
- [x] 共享确认对话框保存预览、UUID、项目和备注；取消不提交，回收/恢复/永久删除均为显式操作。
- [x] 原图预览与分页后台加载，合成渲染检查两种宽度和导航无重复。

```python
assert [x['title'] for x in build_navigation_manifest()] == [
    '任务', '账号', '完成检查', '自动辅助', '工具', '设置']
```

## 4. 自动采集适配

文件：`src/evidence/service.py` 及 DailyTask、WeeklyBossTask、GardenTask 的确证点；审查 NightmareNestTask、AutoAbyssTask 的可用结果边界。

接口：`record_task_evidence(task, project_id, status, reason, frame=None, **details)` 仅在可信绑定存在时提交；失败不阻断生产任务。服务不存在时不创建测试用真实仓库。

- [x] 每个适配点写单独的状态断言与故障不影响主流程测试。
- [x] 活跃度使用刚识别的结果；乐园使用目标达成 OCR；周本在 remaining 已读且退出前采图。
- [x] 战令仅执行领取动作、聚落只有逐目标计数、深塔多层扫描不等于本期完成；首版保留手动入口并记录限制。
- [x] 弹琴和第二索拉首版明确为手动，不从运行时间/按键次数推断完成。

## 5. 验证和发布

文件：run_tests.ps1、导航/UI 测试、scripts/render_flat_ui.py、config.py、更新日志和相关文档。

- [x] 同步覆盖目录：`Copy-Item custom_ok/ok/* .venv/Lib/site-packages/ok -Recurse -Force`。
- [x] 新测试登记 runner；全量 104 文件、1098 项（1090 通过、8 跳过）；最后补充测试后定向 100 项通过。
- [x] 六页双宽度离线渲染，检查账号、项目、图片和小窗口；回收/恢复/永久删除使用合成仓库测试。
- [x] 发布文档明确自动接入范围，永久留存、人工归属和未验证限制。
- [ ] 提交、注释标签、GitHub 推送及远端核验：以本任务最终发布回执为准。

验证报告：`test_out/test_runs/20260910-210421-703/`，定向日志 `test_out/completion-final-focused.log`，渲染目录 `tests/output/completion-evidence/`。版本校验为 1.53.00，五语言既有目录无重复项；本次未改变任务配置键或名称。

自审：覆盖状态、周期、UUID、线程、手动入口、永久留存和不误改任务断点；不承诺未知活动自动判定。性能采用分页与后台工作，不增加新的视觉主题或远端服务。
