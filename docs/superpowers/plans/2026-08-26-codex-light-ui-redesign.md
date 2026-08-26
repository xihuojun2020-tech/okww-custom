# Codex 浅色 UI 与五页平铺重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 ok-wuthering-waves 的桌面 UI 固定为浅色 Codex 风格，并把左侧入口收敛为五个一级页面、页面内容直接平铺，同时保持现有任务执行、账号安全和序列联动行为不变。

**Architecture:** 在现有 PySide6/qfluentwidgets 与 `FluentWindow` 上增加一个小型浅色主题注入层和可复用的 `SectionPanel`/`FlatSettingRow` 展示组件；页面逻辑继续持有原有 task、repository、executor 和配置对象，只替换外层布局。`OneTimeTaskTab` 继续负责任务筛选、配置读写和执行回调，改为使用平铺任务行渲染器，页面实例仍由主窗口缓存。

**Tech Stack:** Python 3.12, PySide6, qfluentwidgets, pytest, 现有 ok-script GUI/任务执行器。

**Spec:** `docs/superpowers/specs/2026-08-26-codex-light-ui-redesign.md`

## Global Constraints

- 固定浅色：窗口 `#F7F8FA`，面板 `#FFFFFF`，边框 `#E5E7EB`，主文字 `#1F2328`，次文字 `#656D76`，强调色 `#0969DA`；不得跟随系统切换深色。
- 左侧滚动导航严格只有“通用设置、账号设置、任务、活动、测试功能”，辅助入口（程序设置、关于、重启、调试、日志导出）保留在底部或右上角。
- 页面切换不得销毁页面实例；刷新不得重建任务实例或清掉用户草稿、当前选择和滚动位置。
- 账号保存、序列变更、备份、修订冲突、原子发布、完整性后验检查和失败回滚必须继续调用现有服务。
- 任务配置行创建失败时只标记该行错误并记录日志，其他任务仍显示。
- 账号切换测试 `TestAccountSwitchTask` 继续复用生产多账号切换路径；默认顺序 A1、A3、A4 的既有约束不得改变。
- 本次中等版本从 `1.15.01` 升级到 `1.16.00`；同步 `config.py`、关于页、`更新日志.md`、交接日志和参考文献。
- Python 命令优先使用 `E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe`；编辑使用 `apply_patch`；保留工作区已有未提交改动，不暂存或回滚 `src/account_config_bundle.py`、`tests/TestAccountConfigBundle.py`、`启动okww.bat`、`.superpowers/`、`config_integrity_incidents/`。
- 每个独立任务完成后运行其聚焦测试并提交；全部验证通过后创建 annotated tag `v1.16.00`，推送分支和 tag。

## File Structure and Responsibilities

- Create `src/gui/CodexTheme.py`: 固定浅色 palette、QSS、字体、滚动条和控件焦点/状态样式；公开 `apply_codex_light_theme(app)` 与 `codex_style_sheet()`。
- Create `src/gui/SectionPanel.py`: 统一区块标题、说明、边框圆角和内容布局；公开 `SectionPanel(title, description="", parent=None)`、`add_widget(widget, stretch=0)`、`add_row(label, control, description="", error=None)`。
- Create `src/gui/FlatSettingRow.py`: 设置标签、说明、控件和错误状态的横向行组件；公开 `FlatSettingRow(label, control, description="", parent=None)`、`set_error(message)`。
- Modify `custom_ok/ok/gui/MainWindow.py`: 初始化固定浅色主题、统一页面背景和辅助入口样式，保持导航和 executor 生命周期。
- Modify `src/gui/GeneralSettingsTab.py`: 用 `SectionPanel` 纵向平铺四个现有设置对象，不再生成隐藏的多级卡片容器。
- Modify `src/gui/AccountSettingsTab.py`: 去除内部 `QTabWidget`，按账号配置、序列配置、维护区顺序直接加入同一滚动布局。
- Modify `src/gui/ActivityHubTab.py`: 去除内部 `QTabWidget`，同页平铺限时活动与常驻活动两个 `SectionPanel`，继续使用 `classify_task` 和既有 `OneTimeTaskTab` 实例。
- Modify `src/gui/TaskHubTab.py` and `src/gui/TestHubTab.py`: 采用统一平铺任务渲染器并显示页面说明；测试页明确账号切换测试属于多账号每日任务测试。
- Modify `custom_ok/ok/gui/tasks/OneTimeTaskTab.py`: 将任务卡展示拆成平铺渲染路径，保留 `refresh_ui`, `in_current_list`, `delete_script`, log signal 和 TaskCard 配置接口。
- Modify `custom_ok/ok/gui/tasks/ConfigItemFactory.py` and related dialog/card style files only where required to remove深色/渐变/Emoji主视觉并统一控件状态。
- Modify `custom_ok/ok/gui/settings/SettingTab.py`, `custom_ok/ok/gui/about/AboutTab.py`, `src/gui/ConfigIntegrityDialog.py`, `src/gui/DailyProfileDialog.py`: 统一浅色样式、中文界面可见文本和对话框状态色；不改变业务动作。
- Create or modify `tests/TestCodexLightUI.py`: 无需真实游戏/截图的 UI 结构、主题、平铺和页面实例保持测试。
- Modify `config.py`: version `1.15.01` → `1.16.00`。
- Modify `更新日志.md`: 添加 1.16.00 条目。
- Create `交接/Codex浅色UI与五页平铺交接日志_2026-08-26.md`: 记录变更、测试、已知图像基线和回滚方法。
- Modify `docs/references/pc-account-configuration-and-sequences.md` or create `docs/references/codex-light-ui.md`: 记录 Codex palette、ALAS 信息架构参考和 qfluentwidgets API 来源。

### Task 1: Add fixed light theme primitives

**Files:**
- Create: `src/gui/CodexTheme.py`
- Create: `src/gui/SectionPanel.py`
- Create: `src/gui/FlatSettingRow.py`
- Test: `tests/TestCodexLightUI.py`

**Interfaces:**
- `apply_codex_light_theme(app: QApplication) -> None` installs palette and stylesheet and forces `qconfig.theme = Theme.LIGHT` without registering a system-theme callback.
- `codex_style_sheet() -> str` returns a deterministic stylesheet containing the six required colors and 8px/10px spacing rules.
- `SectionPanel(title: str, description: str = "", parent: QWidget | None = None)` exposes `content_layout`, `add_widget(widget, stretch=0)`, and `add_row(...)`.
- `FlatSettingRow(label: str, control: QWidget, description: str = "", parent: QWidget | None = None)` exposes `set_error(message: str | None)` and keeps the control instance unchanged.

- [ ] **Step 1: Write the failing tests**

```python
def test_codex_stylesheet_is_fixed_light():
    from src.gui.CodexTheme import codex_style_sheet
    css = codex_style_sheet()
    assert "#F7F8FA" in css and "#FFFFFF" in css
    assert "#E5E7EB" in css and "#0969DA" in css
    assert "dark" not in css.lower()

def test_section_panel_and_setting_row_keep_public_controls(qtbot):
    from PySide6.QtWidgets import QCheckBox
    from src.gui.SectionPanel import SectionPanel
    from src.gui.FlatSettingRow import FlatSettingRow
    control = QCheckBox()
    panel = SectionPanel("监控与启动", "说明")
    row = panel.add_row("自动启动", control, "测试说明")
    qtbot.addWidget(panel)
    assert row.control is control
    row.set_error("配置无效")
    assert row.error_label.text() == "配置无效"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe -m pytest tests/TestCodexLightUI.py -q`

Expected: FAIL with import errors for `src.gui.CodexTheme`, `SectionPanel`, and `FlatSettingRow`.

- [ ] **Step 3: Write minimal implementation**

Implement the three files with ordinary `QWidget`/`QVBoxLayout`/`QHBoxLayout` and qfluentwidgets-compatible properties. Use a single stylesheet string; do not add a theme framework or dependency. Set palette roles explicitly and make `apply_codex_light_theme` idempotent.

- [ ] **Step 4: Run test to verify it passes**

Run: `E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe -m pytest tests/TestCodexLightUI.py -q`

Expected: PASS for palette/style and component behavior tests.

- [ ] **Step 5: Commit**

```bash
rtk git add src/gui/CodexTheme.py src/gui/SectionPanel.py src/gui/FlatSettingRow.py tests/TestCodexLightUI.py
rtk git commit -m "feat: add fixed light Codex UI primitives"
```

### Task 2: Inject theme and normalize main-window shell

**Files:**
- Modify: `custom_ok/ok/gui/MainWindow.py:1-210, 250-330`
- Modify: `tests/TestMainWindowStartup.py` or `tests/TestFiveSectionMainWindow.py`
- Test: `tests/TestCodexLightUI.py`

**Interfaces:**
- `MainWindow.__init__` invokes `apply_codex_light_theme(QApplication.instance())` before creating pages.
- Existing `navigate_tab`, `addSubInterface`, restart, settings, about, tray, executor and show/close behavior remain callable with their current signatures.

- [ ] **Step 1: Write the failing tests**

```python
def test_main_window_installs_light_theme_without_system_theme_signal(monkeypatch):
    import custom_ok.ok.gui.MainWindow as module
    calls = []
    monkeypatch.setattr(module, "apply_codex_light_theme", lambda app: calls.append(app))
    window = build_test_main_window(module)
    assert calls == [window.app]
    assert window.navigation_manifest_titles() == ["通用设置", "账号设置", "任务", "活动", "测试功能"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe -m pytest tests/TestCodexLightUI.py::test_main_window_installs_light_theme_without_system_theme_signal -q`

Expected: FAIL because the theme hook and deterministic manifest assertion are absent.

- [ ] **Step 3: Write minimal implementation**

Import the theme helper, call it once at construction, remove the system-theme synchronization callback/automatic dark-mode branch, and add a small `navigation_manifest_titles()` helper used only by tests. Keep bottom auxiliary items and disable page transition animation as already configured.

- [ ] **Step 4: Run test to verify it passes**

Run: `E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe -m pytest tests/TestCodexLightUI.py tests/TestFiveSectionMainWindow.py tests/TestMainWindowStartup.py -q`

Expected: all focused main-window tests pass; existing startup tests retain their baseline assertions.

- [ ] **Step 5: Commit**

```bash
rtk git add custom_ok/ok/gui/MainWindow.py tests/TestCodexLightUI.py tests/TestFiveSectionMainWindow.py tests/TestMainWindowStartup.py
rtk git commit -m "refactor: apply Codex light shell to main window"
```

### Task 3: Flatten the general-settings page

**Files:**
- Modify: `src/gui/GeneralSettingsTab.py`
- Modify: `custom_ok/ok/gui/start/StartTab.py` only for row style hooks if needed
- Modify: `custom_ok/ok/gui/tasks/TriggerTaskTab.py` only for row style hooks if needed
- Test: `tests/TestCodexLightUI.py`

**Interfaces:**
- `GeneralSettingsTab.section_titles` remains `("监控与启动", "实时触发", "游戏快捷键", "全局行为")`.
- `GeneralSettingsTab.start_panel`, `.trigger_panel`, `.hotkey_config`, and `.executor` remain available to `MainWindow` and task notifications.

- [ ] **Step 1: Write the failing tests**

```python
def test_general_settings_has_four_flat_section_panels(qtbot):
    tab = build_general_settings_tab()
    qtbot.addWidget(tab)
    assert tab.section_titles == ("监控与启动", "实时触发", "游戏快捷键", "全局行为")
    assert [panel.title for panel in tab.section_panels] == list(tab.section_titles)
    assert not tab.findChildren(QTabWidget)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe -m pytest tests/TestCodexLightUI.py::test_general_settings_has_four_flat_section_panels -q`

Expected: FAIL because `section_panels` and the new panel ownership are not exposed.

- [ ] **Step 3: Write minimal implementation**

Replace `add_card` calls with `SectionPanel` instances added directly to the page scroll layout. Add existing StartTab, TriggerTaskTab, hotkey controls and behavior controls to each panel without copying config objects. Use `FlatSettingRow` only where a raw control needs a label; preserve signals and option objects.

- [ ] **Step 4: Run test to verify it passes**

Run: `E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe -m pytest tests/TestCodexLightUI.py tests/TestFeatureSet.py -q`

Expected: PASS and unchanged feature/config behavior.

- [ ] **Step 5: Commit**

```bash
rtk git add src/gui/GeneralSettingsTab.py custom_ok/ok/gui/start/StartTab.py custom_ok/ok/gui/tasks/TriggerTaskTab.py tests/TestCodexLightUI.py
rtk git commit -m "refactor: flatten general settings sections"
```

### Task 4: Flatten account settings without changing transactions

**Files:**
- Modify: `src/gui/AccountSettingsTab.py`
- Modify: `src/gui/AccountConfigTab.py` and `src/gui/SequenceManagementTab.py` only for outer-style hooks and section titles
- Modify: `custom_ok/ok/gui/settings/SettingTab.py` only for maintenance section styling
- Test: `tests/TestCodexLightUI.py`, `tests/TestAccountManagementTabs.py`, `tests/TestAccountDeletion.py`

**Interfaces:**
- `AccountSettingsTab.account_tab`, `.sequence_tab`, and `.maintenance_tab` remain the same object types.
- Existing repository save/delete/reorder methods and confirmation dialogs are not renamed or bypassed.

- [ ] **Step 1: Write the failing tests**

```python
def test_account_settings_is_flat_and_keeps_three_sections(qtbot):
    tab = build_account_settings_tab()
    qtbot.addWidget(tab)
    assert [section.title for section in tab.section_panels] == [
        "账号配置", "序列配置", "导入导出、备份与完整性"
    ]
    assert not tab.findChildren(QTabWidget)
    assert tab.account_tab.repository is not None
    assert tab.sequence_tab.repository is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe -m pytest tests/TestCodexLightUI.py::test_account_settings_is_flat_and_keeps_three_sections -q`

Expected: FAIL because the current page creates a `QTabWidget` and no `section_panels` list.

- [ ] **Step 3: Write minimal implementation**

Remove the `QTabWidget`; create three `SectionPanel`s in one vertical scroll layout and add the existing child widgets directly. Set child page margins to zero or use their existing layouts so controls do not get duplicated. Keep maintenance-only `SettingTab` behavior, CAS revision checks, backup calls, and delete second confirmation intact.

- [ ] **Step 4: Run test to verify it passes**

Run: `E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe -m pytest tests/TestCodexLightUI.py tests/TestAccountManagementTabs.py tests/TestAccountDeletion.py tests/TestSequenceRepository.py -q`

Expected: PASS; deletion and sequence membership tests remain green.

- [ ] **Step 5: Commit**

```bash
rtk git add src/gui/AccountSettingsTab.py src/gui/AccountConfigTab.py src/gui/SequenceManagementTab.py custom_ok/ok/gui/settings/SettingTab.py tests/TestCodexLightUI.py tests/TestAccountManagementTabs.py tests/TestAccountDeletion.py
rtk git commit -m "refactor: flatten account settings sections"
```

### Task 5: Flatten task/activity/test hubs with one task renderer

**Files:**
- Modify: `custom_ok/ok/gui/tasks/OneTimeTaskTab.py`
- Modify: `src/gui/TaskHubTab.py`
- Modify: `src/gui/ActivityHubTab.py`
- Modify: `src/gui/TestHubTab.py`
- Modify: `custom_ok/ok/gui/tasks/TaskCard.py` and `custom_ok/ok/gui/tasks/ConfigItemFactory.py` only for shared row styling
- Test: `tests/TestCodexLightUI.py`, `tests/TestTaskNavigationClassification.py`, `tests/TestNavigationSections.py`, `tests/TestAccountSwitch.py`

**Interfaces:**
- `OneTimeTaskTab.refresh_ui()` continues to update only presentation widgets and preserves task instances, config objects, logs and callbacks.
- `OneTimeTaskTab.in_current_list(task) -> bool`, `delete_script()` and `_append_log(level_no, message)` keep their current behavior.
- `TaskHubTab.task_tab`, `ActivityHubTab.limited_tab`, `ActivityHubTab.permanent_tab`, and `TestHubTab.task_tab` remain available to MainWindow and notifications.

- [ ] **Step 1: Write the failing tests**

```python
def test_activity_and_account_pages_have_no_nested_tabs(qtbot):
    activity = build_activity_hub_tab()
    task = build_task_hub_tab()
    test = build_test_hub_tab()
    for widget in (activity, task, test):
        qtbot.addWidget(widget)
    assert not activity.findChildren(QTabWidget)
    assert [panel.title for panel in activity.section_panels] == ["限时活动", "常驻活动"]
    assert test.account_switch_description == "账号切换测试（多账号每日任务测试）"

def test_refresh_ui_keeps_task_object_and_filters_window_diagnostic(qtbot):
    tab = build_one_time_task_tab()
    original = fake_executor_task()
    tab.tasks = [original]
    tab._append_log(20, "do_update_window_size changed")
    tab._append_log(20, "A3 登录完成")
    tab.refresh_ui()
    assert tab.executor_task_identity(original) is original
    assert "do_update_window_size" not in tab.log_panel_text.toPlainText()
    assert "A3 登录完成" in tab.log_panel_text.toPlainText()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe -m pytest tests/TestCodexLightUI.py::test_activity_and_account_pages_have_no_nested_tabs tests/TestCodexLightUI.py::test_refresh_ui_keeps_task_object_and_filters_window_diagnostic -q`

Expected: FAIL on nested tabs/renderer identity helper and the current card-only layout.

- [ ] **Step 3: Write minimal implementation**

Add a compact flat task-row/widget wrapper around the existing `TaskCard` content, using `SectionPanel` for grouping and no second tab layer. Keep the current task filtering by `classify_task`, activity category and visibility. On refresh, remove only row widgets, reuse task objects and reconnect no business signals. Put the persistent log panel after all task rows. For activities, instantiate the two existing task tabs once and mount each under its own section. For tests, add a visible Chinese description naming the multi-account test relationship.

- [ ] **Step 4: Run test to verify it passes**

Run: `E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe -m pytest tests/TestCodexLightUI.py tests/TestTaskNavigationClassification.py tests/TestNavigationSections.py tests/TestAccountSwitch.py -q`

Expected: PASS; activity classification keeps “悲鸣行动：无音危机” in 常驻活动 and account-switch test still uses production methods.

- [ ] **Step 5: Commit**

```bash
rtk git add custom_ok/ok/gui/tasks/OneTimeTaskTab.py src/gui/TaskHubTab.py src/gui/ActivityHubTab.py src/gui/TestHubTab.py custom_ok/ok/gui/tasks/TaskCard.py custom_ok/ok/gui/tasks/ConfigItemFactory.py tests/TestCodexLightUI.py tests/TestTaskNavigationClassification.py tests/TestNavigationSections.py tests/TestAccountSwitch.py
rtk git commit -m "refactor: flatten task activity and test hubs"
```

### Task 6: Normalize auxiliary dialogs and program shell styling

**Files:**
- Modify: `custom_ok/ok/gui/settings/SettingTab.py`
- Modify: `custom_ok/ok/gui/about/AboutTab.py`
- Modify: `src/gui/ConfigIntegrityDialog.py`
- Modify: `src/gui/DailyProfileDialog.py`
- Modify: `custom_ok/ok/gui/settings/GlobalConfigCard.py` and `custom_ok/ok/gui/about/VersionCard.py` only where their controls expose old theme colors
- Test: `tests/TestCodexLightUI.py`, `tests/TestConfigIntegrity.py`, `tests/TestScheduleSupport.py`

**Interfaces:**
- Program settings remains a bottom auxiliary route and continues to save language/window/update settings.
- About page continues to show version/update history and upstream notices.
- Integrity and profile dialogs retain their existing accept/reject, backup and rollback callbacks.

- [ ] **Step 1: Write the failing tests**

```python
def test_auxiliary_widgets_use_codex_light_tokens(qtbot):
    for widget in (build_setting_tab(), build_about_tab(), build_integrity_dialog()):
        qtbot.addWidget(widget)
        assert "#FFFFFF" in widget.styleSheet() or widget.palette().window().color().name().lower() == "#ffffff"
    assert build_setting_tab().is_bottom_auxiliary is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe -m pytest tests/TestCodexLightUI.py::test_auxiliary_widgets_use_codex_light_tokens -q`

Expected: FAIL because auxiliary widgets still inherit mixed qfluentwidgets/system theme styling and expose no auxiliary marker.

- [ ] **Step 3: Write minimal implementation**

Apply the shared stylesheet/palette to these widgets, replace hard-coded dark/gradient colors with palette roles or required tokens, and add only a read-only `is_bottom_auxiliary = True` marker to `SettingTab`. Keep all existing button callbacks and data services unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe -m pytest tests/TestCodexLightUI.py tests/TestConfigIntegrity.py tests/TestScheduleSupport.py -q`

Expected: PASS with dialog behavior unchanged.

- [ ] **Step 5: Commit**

```bash
rtk git add custom_ok/ok/gui/settings/SettingTab.py custom_ok/ok/gui/about/AboutTab.py src/gui/ConfigIntegrityDialog.py src/gui/DailyProfileDialog.py custom_ok/ok/gui/settings/GlobalConfigCard.py custom_ok/ok/gui/about/VersionCard.py tests/TestCodexLightUI.py
rtk git commit -m "style: normalize auxiliary dialogs for light UI"
```

### Task 7: Version, release notes, handoff and references

**Files:**
- Modify: `config.py`
- Modify: `custom_ok/ok/gui/about/AboutTab.py`
- Modify: `更新日志.md`
- Create: `交接/Codex浅色UI与五页平铺交接日志_2026-08-26.md`
- Modify or create: `docs/references/codex-light-ui.md`
- Test: `tests/TestCodexLightUI.py`

**Interfaces:**
- Product-facing version is exactly `1.16.00` everywhere.
- Handoff log includes changed files, migration/rollback notes, test commands/results, known pre-existing image-baseline failures and upstream version context.

- [ ] **Step 1: Write the failing test**

```python
def test_release_version_and_notes_are_synchronized():
    from config import version
    assert version == "1.16.00"
    about = Path("custom_ok/ok/gui/about/AboutTab.py").read_text(encoding="utf-8")
    changelog = Path("更新日志.md").read_text(encoding="utf-8")
    assert "V1.16.00" in about and "1.16.00" in changelog
```

- [ ] **Step 2: Run test to verify it fails**

Run: `E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe -m pytest tests/TestCodexLightUI.py::test_release_version_and_notes_are_synchronized -q`

Expected: FAIL because the repository is still on `1.15.01`.

- [ ] **Step 3: Write minimal implementation**

Set `config.py` version to `1.16.00`, prepend the matching About/update-log entry, record UI token values and references, and write the Chinese handoff with rollback instructions (`git revert` before release, restore previous tag/config after release), exact focused test commands, and explicit note that user-owned dirty files were preserved.

- [ ] **Step 4: Run test to verify it passes**

Run: `E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe -m pytest tests/TestCodexLightUI.py -q`

Expected: PASS and no version mismatch.

- [ ] **Step 5: Commit**

```bash
rtk git add config.py custom_ok/ok/gui/about/AboutTab.py 更新日志.md "交接/Codex浅色UI与五页平铺交接日志_2026-08-26.md" docs/references/codex-light-ui.md tests/TestCodexLightUI.py
rtk git commit -m "release: Codex light UI v1.16.00"
```

### Task 8: Full verification and publish

**Files:**
- Test only: all changed UI tests plus full repository test suite

**Interfaces:**
- No production interface changes are allowed in this verification task.

- [ ] **Step 1: Run focused UI and behavior regression**

Run: `E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe -m pytest tests/TestCodexLightUI.py tests/TestFiveSectionMainWindow.py tests/TestMainWindowStartup.py tests/TestAccountManagementTabs.py tests/TestAccountDeletion.py tests/TestSequenceRepository.py tests/TestTaskNavigationClassification.py tests/TestNavigationSections.py tests/TestAccountSwitch.py tests/TestConfigIntegrity.py -q`

Expected: PASS; any image-baseline failures must be listed as pre-existing and not silently ignored.

- [ ] **Step 2: Run compile and diff checks**

Run: `E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe -m compileall -q src custom_ok`

Run: `rtk git diff --check`

Expected: zero compile or whitespace errors.

- [ ] **Step 3: Run the full suite and record baseline exceptions**

Run: `E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe -m pytest -q`

Expected: record pass/skip/fail counts in the handoff log; compare any screenshot/image failures to the pre-UI-change baseline and do not classify known baseline failures as regressions.

- [ ] **Step 4: Review repository state**

Run: `rtk git status --short`

Expected: only intended UI/version/document files are staged; user-owned dirty files listed in Global Constraints remain unstaged and unchanged.

- [ ] **Step 5: Create annotated release tag and push**

```bash
rtk git tag -a v1.16.00 -m "v1.16.00 Codex light UI and five flat pages"
rtk git push origin master
rtk git push origin v1.16.00
```

Expected: branch and tag are accepted by GitHub; report commit SHA, tag and test summary in the final handoff.

## Self-Review Checklist

- [ ] Spec sections 1–8 each map to at least one task above.
- [ ] Search the plan for unresolved placeholder markers and remove any placeholder.
- [ ] Confirm signatures are consistent: `apply_codex_light_theme`, `codex_style_sheet`, `SectionPanel.add_row`, `FlatSettingRow.set_error`, and the existing page/task attributes.
- [ ] Confirm no task introduces a second account-selection implementation, Android/MuMu/ADB behavior, or a new dependency.
- [ ] Confirm version, About text, changelog, handoff and references all name `1.16.00`.
