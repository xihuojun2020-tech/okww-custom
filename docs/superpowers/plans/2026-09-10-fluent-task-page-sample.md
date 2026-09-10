# Fluent Task Page Sample Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付任务页原版 Fluent 风格样板，保留任务启动、默认折叠、配置和分类语义。

**Architecture:** 复用现有 TaskCard 与 ConfigContentMixin，在任务页显式启用局部样板外观，不创建第二套任务实现。主题和其他四页不在本批迁移。样板获用户视觉确认后，另行制定公共主题与其余页面的迁移计划。

**Tech Stack:** Python、PySide6、QFluentWidgets、unittest、PowerShell；使用 `.\.venv\Scripts\python.exe`。

**Spec:** `docs/superpowers/specs/2026-09-10-original-fluent-ui-design.md`（用户于本任务确认）。

## Global Constraints

- 现有 Python/PySide6/QFluentWidgets 栈不变，不引入网页容器、新 UI 框架或新依赖。
- 首次创建所有可折叠区域均收起；分类标题本身不折叠。
- 普通状态刷新保留展开和用户输入，不触发 enable/disable；继续屏蔽程序化开关同步信号。
- 不覆盖已完成的 1.48.00 自动战斗恢复及 1.49.00 深塔修复，不纳入已有 docs/reviews 删除。
- 不启动游戏、不输入真实账号，不上传测试诊断或发布 NAS 包。
- 样板仅覆盖设计的第一交付点；完整主题、账号标签切换、其他四页迁移仍未完成。
- 当前版本 1.49.00；代码交付前重新核对版本，未被其他工作推进时更新到 1.50.00。仅文档提交不递增版本。
- 本环境未列出上文两项执行子技能；不可假称已使用。选择执行方式后可按本计划逐项手工执行并记录结果。

## 文件职责

| 文件 | 本批职责 |
| --- | --- |
| `custom_ok/ok/gui/tasks/TaskCard.py` | 增加可选 `fluent_sample=False` 构造参数，样板布局适配；原启停方法不改 |
| `custom_ok/ok/gui/tasks/OneTimeTaskTab.py` | 增加同名可选参数，只向其创建的 TaskCard 传递，并保留活动摘要 |
| `src/gui/TaskHubTab.py` | 唯一开启样板参数的页面，压缩外层间距 |
| `tests/TestFlatUI.py` | 样板说明、默认折叠、独立操作和非样板隔离测试 |
| `scripts/render_flat_ui.py` | 可选离线状态注入，保留原默认行为 |
| `config.py` 与下文列出的文档 | 样板版本、验收及明确的剩余工作 |

`ConfigCard.py`、`DisclosureHeader.py` 的共用行为原则上不改。使用其既有 card、contentLabel、summary_label、viewLayout、rootLayout 完成局部适配。发现必须改变共用接口时先记录影响并补齐非样板回归，不能静默扩大范围。

### Task 1: 可隔离的完整任务卡片

**Interfaces:** Consumes `TaskCard(task, onetime)`；produces `TaskCard(task, onetime, *, fluent_sample=False)`，默认行为不变。

- [ ] **Step 1: 在 TestFlatUI 类加入红灯测试。**

```python
def test_fluent_sample_keeps_description_visible_when_collapsed(self):
    from ok.gui.tasks.TaskCard import TaskCard
    task = example_task()
    with patch.object(og, 'app', SimpleNamespace(tr=str)), \
         patch.object(og, 'executor', SimpleNamespace(waiting_for_task=lambda _: '')):
        card = TaskCard(task, True, fluent_sample=True)
        card.resize(760, card.sizeHint().height())
        card.show()
        self.app.processEvents()
        self.assertFalse(card.isExpand)
        self.assertTrue(card.card.contentLabel.isVisible())
        self.assertFalse(card.view.isVisible())
        card.setExpand(True)
        self.assertTrue(card.view.isVisible())
        card.close()
        card.deleteLater()
```

- [ ] **Step 2: 同步当前覆盖并运行测试，确认失败于未知构造参数。**

```powershell
Copy-Item -Path custom_ok/ok/* -Destination .venv/Lib/site-packages/ok -Recurse -Force
.\.venv\Scripts\python.exe scripts/run_test_file.py tests/TestFlatUI.py --timeout 180
```

- [ ] **Step 3: 在 TaskCard 构造末尾实现局部布局。** 保留原方法及状态绑定，仅在参数为 true 时执行：

```python
self.setObjectName('fluentTaskSample')
self.viewLayout.removeWidget(self.card.contentLabel)
self.card.text_layout.addWidget(self.card.contentLabel)
self.rootLayout.setContentsMargins(0, 0, 0, 0)
self.rootLayout.setSpacing(0)
self.card.setMinimumHeight(76)
self.card.layout_row.setContentsMargins(16, 12, 12, 12)
self.viewLayout.setContentsMargins(16, 12, 16, 16)
self.setStyleSheet('''
    QWidget#fluentTaskSample { background: #FFFFFF;
        border: 1px solid #E5E7EB; border-radius: 8px; }
    QWidget#fluentTaskSample QWidget#disclosureHeader {
        background: transparent; border: 0; border-radius: 8px; }
    QWidget#fluentTaskSample QWidget#disclosureHeader:hover {
        background: #F0F1F3; }
''')
```

这是样板局部浅色样式，不作为最终主题实现。contentLabel 移入标题后必须设置 `WA_TransparentForMouseEvents`，确保说明点击同样展开；详情不能重复显示说明。不改 task.name 或保存字段。

- [ ] **Step 4: 扩展现有独立点击测试，在普通和样板两种构造参数下分别运行。**

```python
# 在既有 test_header_clicks_and_actions_are_independent 的断言主体外
# 使用 subTest，并将其原 TaskCard 构造传入对应参数。
for sample in (False, True):
    with self.subTest(fluent_sample=sample):
        card = TaskCard(example_task(), True, fluent_sample=sample)
        # 执行原完整点击断言主体，不能删除原断言。
```

另外对未启用样板的卡片断言 `objectName() == 'configSection'`，收起时 `contentLabel.isVisible()` 为 false。参数显示、条件字段、长文本和刷新保留测试继续运行。测试全部通过后保留待最终版本提交的改动。

### Task 2: 任务页密度与分类适配

**Interfaces:** Consumes Task 1 constructor；produces `OneTimeTaskTab(..., fluent_sample=False)`。仅 `TaskHubTab` 传 true。

- [ ] **Step 1: 检查所有 TaskCard 和 OneTimeTaskTab 调用，确认可选参数不破坏旧调用。**

```powershell
rg -n 'TaskCard\(|OneTimeTaskTab\(' src custom_ok tests
```

- [ ] **Step 2: 保存并传递样板参数，在 TaskHubTab 开启。**

```python
# OneTimeTaskTab.__init__ 新增 keyword 参数并保存。
self.fluent_sample = fluent_sample
# refresh_ui 创建卡片。
task_card = TaskCard(task, True, fluent_sample=self.fluent_sample)
# TaskHubTab.__init__。
self.task_tab = OneTimeTaskTab(section=TASKS, group_tasks=True,
                              fluent_sample=True)
```

保留活动现有 `card.set_summary(...)`，完整说明使用独立 contentLabel，不被活动分类覆盖。保留 section_panels 接口；只将任务页外层 layout margins 调至 0、spacing 调至 8，去掉该外层局部分隔线，不改全局 SectionPanel。TaskTab 的分组和数据排序保持。

- [ ] **Step 3: 在现有页面分类测试加入样板作用域断言。**

```python
# 在已有真实 MainWindow fixture 和卡片分类断言后添加。
for card in window.task_hub_tab.task_tab.card_widgets:
    self.assertEqual(card.objectName(), 'fluentTaskSample')
for card in window.assistant_hub_tab.trigger_panel.card_widgets:
    self.assertEqual(card.objectName(), 'configSection')
```

使用测试中的实际窗口变量名；断言目标和语义不变。依次运行 `TestFlatUI.py`、`TestTaskNavigationClassification.py`、`TestFiveSectionMainWindow.py`，通过后检查 diff 中无任务注册或业务操作变化。

### Task 3: 截图、完整验证与版本交付

**Interfaces:** Consumes actual five-page renderer；produces screenshots and documented test results, no game actions。

- [ ] **Step 1: 为 renderer 添加可选 `OKWW_UI_SAMPLE_STATE`，仅在模拟任务列表构造后注入任务状态。**

```python
sample_state = os.environ.get('OKWW_UI_SAMPLE_STATE', '')
if sample_state:
    sample_task = executor.onetime_tasks[0]
    sample_task._enabled = sample_state == 'running'
    sample_task.running = sample_state == 'running'
    if sample_state == 'error':
        sample_task.info['Error'] = '离线布局测试：模拟任务异常'
```

错误展示必须读取既有 UI 状态接口；若 info 不出现在收起状态，截图标注“模拟错误详情”，不能把未运行说成错误徽标。禁止为截图调用 enable、run 或真实错误上传。

- [ ] **Step 2: 用真实控件渲染默认、展开、运行及错误状态；每次清理本次设定的环境变量。**

```powershell
.\.venv\Scripts\python.exe scripts/render_flat_ui.py test_out/fluent-sample/collapsed
$env:OKWW_UI_EXPAND_ALL = '1'
.\.venv\Scripts\python.exe scripts/render_flat_ui.py test_out/fluent-sample/expanded
Remove-Item Env:OKWW_UI_EXPAND_ALL
$env:OKWW_UI_SAMPLE_STATE = 'running'
.\.venv\Scripts\python.exe scripts/render_flat_ui.py test_out/fluent-sample/running
$env:OKWW_UI_SAMPLE_STATE = 'error'
.\.venv\Scripts\python.exe scripts/render_flat_ui.py test_out/fluent-sample/error
Remove-Item Env:OKWW_UI_SAMPLE_STATE
```

使用 view_image 检查 TaskHubTab 760/1100 图：同一张卡片边界、说明可见、操作不被挤压、无内层滚动。以 `QT_SCALE_FACTOR=1.5` 和 `2` 再运行渲染并恢复环境；不把离线像素缩放当真实设备实测。其他四页截图与现有基线对照，发现样板外样式变化则收窄 selector。

- [ ] **Step 3: 更新版本和用户文档，明确仅任务页样板完成。**

修改 `config.py`、`README.md`、`更新日志.md`、`docs/README.md`、`docs/程序结构说明.md`、`docs/项目交接与新对话上下文.md`、`docs/references/flat-ui.md`、`docs/references/ui-disclosure-verification.md`。记录实际测试计数和截图路径，不填写预期通过数。将本计划完成项目勾选，设计文档状态改为样板待视觉确认。

- [ ] **Step 4: 全量回归及发布检查。**

```powershell
.\run_tests.ps1 -Group all
.\.venv\Scripts\python.exe scripts/validate_release.py --tag v1.50.00
git diff --check
```

若基线版本已经变化，用本批实际版本替换上述标签。所有测试通过后依照仓库 deploy 技能逐文件暂存、提交、创建匹配注释标签、推送并核对远端。不能包含 docs/reviews 删除，也不能宣称推送等于安装器已完成。

- [ ] **Step 5: 展示任务页样板截图，等待用户确认再启动后续页面迁移。**

## 自检

本计划覆盖设计阶段一；主题适配、账号双标签、其他四页统一样式有意留待样板确认后的后续计划。TaskCard 默认参数为 false，只有任务页主动开启，确保中间交付可独立验证。全部操作保持既有业务入口，文档阶段无代码版本变更。
