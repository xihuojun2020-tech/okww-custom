# Five-Section Navigation and Account Management Implementation Plan

> **For agentic workers:** Execute this plan task-by-task in the current root session. This repository's routing instructions prohibit subagent delegation unless the user explicitly requests it. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current fragmented navigation with five integrated PC pages, add safe cascade account deletion, fix silent sequence deletion, simplify account editing, and correct task/activity/test classification.

**Architecture:** `MainWindow` will create exactly five project-owned hub tabs and reuse existing OK task/config widgets inside them. Account and sequence writes remain behind `AccountRepository`; destructive account deletion is one rollback-capable operation, while GUI callbacks consistently surface progress, success, and sanitized errors.

**Tech Stack:** Python 3.12, PySide6, qfluentwidgets, JSON, unittest, repository-local `.venv`.

**Spec:** `docs/superpowers/specs/2026-08-25-five-section-navigation-and-account-management-design.md`

## Global Constraints

- The scroll navigation contains exactly: 通用设置、账号设置、任务、活动、测试功能.
- 程序设置、重启程序 and 关于 remain bottom items; Schedule is hidden.
- No Android, MuMu, ADB, device-binding, or emulator code.
- UUID, login identities, passwords, and tokens remain read-only and redacted.
- Account deletion requires two confirmations, backs up first, removes sequence references, removes account runtime state, and rolls back all affected files on failure.
- `TestAccountSwitchTask` continues to reuse the production switch/snapshot path.
- Use `E:\AI work\ok-wuthering-waves-master\.venv\Scripts\python.exe` for Python commands.
- Preserve unrelated dirty-worktree changes; do not stage `config_integrity_incidents/` or unrelated existing edits.
- This is a medium release. Use version `1.14.00` unless that tag becomes occupied before release; never move an existing tag.

---

### Task 1: Navigation Section Metadata and Five-Hub Skeleton

**Files:**
- Create: `src/gui/navigation_sections.py`
- Create: `tests/TestNavigationSections.py`

**Interfaces:**
- Produces: `NavigationSection` enum/string constants, `classify_task(task) -> str`, `build_navigation_manifest(executor, config) -> tuple[dict, ...]`.
- Consumers: all five hub tabs and `MainWindow`.

- [ ] **Step 1: Write failing manifest tests**

```python
def test_manifest_has_exactly_five_scroll_entries():
    manifest = build_navigation_manifest(fake_executor(), {})
    assert [item["title"] for item in manifest] == [
        "通用设置", "账号设置", "任务", "活动", "测试功能"
    ]

def test_schedule_and_old_standalone_entries_are_absent():
    routes = {item["route"] for item in build_navigation_manifest(fake_executor(), {})}
    assert routes == {"general", "accounts", "tasks", "activities", "tests"}
```

- [ ] **Step 2: Run the new test and confirm the module is missing**

Run: `rtk .\.venv\Scripts\python.exe -m unittest tests.TestNavigationSections`

Expected: FAIL with `ModuleNotFoundError: src.gui.navigation_sections`.

- [ ] **Step 3: Implement the pure manifest and classification boundary**

```python
GENERAL, ACCOUNTS, TASKS, ACTIVITIES, TESTS = (
    "general", "accounts", "tasks", "activities", "tests"
)

def classify_task(task):
    return getattr(task, "navigation_section", None) or (
        TESTS if getattr(task, "group_name", "") == "🧪 测试功能" else
        ACTIVITIES if getattr(task, "group_name", "") in {"限时活动", "常驻活动"} else
        TASKS
    )

def build_navigation_manifest(_executor, _config):
    return tuple({"route": route, "title": title} for route, title in (
        (GENERAL, "通用设置"), (ACCOUNTS, "账号设置"), (TASKS, "任务"),
        (ACTIVITIES, "活动"), (TESTS, "测试功能"),
    ))
```

- [ ] **Step 4: Run manifest tests**

Run: `rtk .\.venv\Scripts\python.exe -m unittest tests.TestNavigationSections`

Expected: PASS.

- [ ] **Step 5: Commit the pure routing boundary**

```powershell
rtk git add -- src/gui/navigation_sections.py tests/TestNavigationSections.py
rtk git commit -m "refactor: establish five-section navigation"
```

---

### Task 2: Integrated General Settings Page

**Files:**
- Create: `src/gui/GeneralSettingsTab.py`
- Create: `tests/TestGeneralSettingsTab.py`
- Modify: `custom_ok/ok/gui/MainWindow.py`
- Modify: `custom_ok/ok/gui/settings/SettingTab.py`

**Interfaces:**
- Consumes: existing `StartTab`, visible trigger tasks, `GlobalConfigCard`, game hotkey config, notification/data/backup config objects.
- Produces: `GeneralSettingsTab(config, exit_event, executor, global_config)` with one route and four sections.

- [ ] **Step 1: Write failing ownership tests**

```python
def test_general_page_owns_four_sections_and_reuses_config_objects():
    tab = make_general_tab()
    assert tab.section_titles == ("监控与启动", "实时触发", "游戏快捷键", "全局行为")
    assert tab.hotkey_config is fake_hotkey_config
    assert tab.trigger_tasks == tuple(fake_executor.trigger_tasks)
```

- [ ] **Step 2: Run the test and confirm `GeneralSettingsTab` is missing**

Run: `rtk .\.venv\Scripts\python.exe -m unittest tests.TestGeneralSettingsTab`

Expected: FAIL on import.

- [ ] **Step 3: Implement one scroll page with four cards/expandable groups**

Use existing widgets rather than copying configuration state:

```python
class GeneralSettingsTab(CustomTab):
    section_titles = ("监控与启动", "实时触发", "游戏快捷键", "全局行为")

    def __init__(self, config, exit_event, executor, global_config):
        super().__init__()
        self.start_panel = StartTab(config, exit_event)
        self.trigger_tasks = tuple(task for task in executor.trigger_tasks if task.visible)
        self.hotkey_config = global_config.get_config("Game Hotkey")
        # Add the existing panels/cards under the four section headings.
```

`StartTab` keeps window/capture/interaction/start/log controls. Trigger task cards keep their original Config objects. Game Hotkey is removed from independent `show_at_tab` navigation and rendered here. Notifications, warehouse, backup, and global behavior cards render in the fourth section.

- [ ] **Step 4: Restrict `SettingTab` to program-only settings**

Keep language, theme, update/application options and other program-shell settings. Remove account import/export/backup cards and operational global config cards because Tasks 3 and 2 own them. Rename its navigation label to `程序设置` in `MainWindow`.

- [ ] **Step 5: Run page, settings, and global-config regression tests**

Run: `rtk .\.venv\Scripts\python.exe -m unittest tests.TestGeneralSettingsTab tests.TestMainWindowStartup tests.TestConfigBackup`

Expected: PASS.

- [ ] **Step 6: Commit general settings**

```powershell
rtk git add -- src/gui/GeneralSettingsTab.py tests/TestGeneralSettingsTab.py custom_ok/ok/gui/MainWindow.py custom_ok/ok/gui/settings/SettingTab.py
rtk git commit -m "feat: integrate general automation settings"
```

---

### Task 3: Transactional Cascade Account Deletion

**Files:**
- Modify: `src/account_repository.py`
- Modify: `src/sequence_repository.py`
- Modify: `src/account_config_editor.py`
- Create: `tests/TestAccountDeletion.py`
- Modify: `tests/TestAccountRepositoryRuntime.py`

**Interfaces:**
- Produces: `AccountDeletionPreview(profile_id, account_label, sequence_ids, runtime_present)`, `AccountRepository.preview_profile_deletion(profile_id)`, `AccountRepository.delete_profile_cascade(profile_id, *, expected_revision)`, `AccountConfigEditor.delete_profile(scope, *, confirmed_account_label)`.
- Consumes: current master transaction writer, account backup boundary, runtime-state paths, integrity post-check.

- [ ] **Step 1: Write failing deletion and rollback tests**

```python
def test_delete_removes_profile_from_every_sequence_and_runtime(tmp_path):
    repo = trusted_repository(tmp_path, profiles=3, references={"S1": [A1, A3], "S2": [A3]})
    preview = repo.preview_profile_deletion(A3)
    assert preview.sequence_ids == ("S1", "S2")
    repo.delete_profile_cascade(A3, expected_revision=repo.load_profile(A3).revision)
    assert A3 not in repo.list_profile_ids()
    assert all(A3 not in repo.load_sequence(name).profile_ids for name in ("S1", "S2"))
    assert not repo._account_state_path(A3).exists()

def test_delete_failure_restores_master_working_runtime_and_account_state(tmp_path):
    before = snapshot_bytes(repo)
    repo.deletion_postcheck_hook = lambda: (_ for _ in ()).throw(RuntimeError("forced"))
    with self.assertRaises(RuntimeError):
        repo.delete_profile_cascade(A3, expected_revision=revision)
    assert snapshot_bytes(repo) == before
```

Also cover stale revision, last-account protection, wrong confirmation label, and backup-before-delete ordering.

- [ ] **Step 2: Run deletion tests and confirm methods are missing**

Run: `rtk .\.venv\Scripts\python.exe -m unittest tests.TestAccountDeletion`

Expected: FAIL with missing preview/delete APIs.

- [ ] **Step 3: Implement preview and one rollback-capable repository operation**

```python
@dataclass(frozen=True)
class AccountDeletionPreview:
    profile_id: str
    account_label: str
    sequence_ids: tuple[str, ...]
    runtime_present: bool

def delete_profile_cascade(self, profile_id, *, expected_revision):
    # validate UUID, revision, and remaining-account count
    # capture master/working/runtime/account-state bytes
    # create account backup
    # remove UUID from profiles and every sequence
    # publish/rebuild/check integrity
    # delete account runtime state
    # restore every captured byte on any exception
```

Use the existing lock, unchecked master writer only inside the established transaction boundary, `atomic_write_json` for protected projections, and the current integrity post-check. Do not implement a force-delete bypass.

- [ ] **Step 4: Add editor confirmation boundary**

`AccountConfigEditor.delete_profile` must compare the scope revision and exact displayed short name, then delegate once to `delete_profile_cascade`. It must not separately mutate sequences.

- [ ] **Step 5: Run deletion, repository, integrity, sequence, and bundle tests**

Run: `rtk .\.venv\Scripts\python.exe -m unittest tests.TestAccountDeletion tests.TestAccountRepositoryRuntime tests.TestSequenceRepository tests.TestConfigIntegrity tests.TestAccountConfigBundle`

Expected: PASS.

- [ ] **Step 6: Commit deletion service**

```powershell
rtk git add -- src/account_repository.py src/sequence_repository.py src/account_config_editor.py tests/TestAccountDeletion.py tests/TestAccountRepositoryRuntime.py
rtk git commit -m "feat: add transactional account deletion"
```

---

### Task 4: Account Settings Hub, Structured Chinese Editor, and Sequence Bug Fix

**Files:**
- Create: `src/gui/AccountSettingsTab.py`
- Create: `src/account_field_metadata.py`
- Modify: `src/gui/AccountConfigTab.py`
- Modify: `src/gui/SequenceManagementTab.py`
- Modify: `custom_ok/ok/gui/MainWindow.py`
- Create: `tests/TestAccountSettingsTab.py`
- Modify: `tests/TestAccountConfigEditor.py`
- Modify: `tests/TestSequenceRepository.py`

**Interfaces:**
- Produces: `AccountFieldMetadata(path, label, help_text, editor_type, options, affects_identity, read_only)`, `editable_account_fields(task)`, `AccountSettingsTab` with `账号配置/序列配置/数据维护` internal tabs, and common `run_ui_action(label, callback)` error boundary.
- Consumes: Task 3 deletion APIs and existing import/export/backup/integrity callbacks.

- [ ] **Step 1: Write failing field metadata and UI-action tests**

```python
def test_identity_fields_are_read_only_and_task_fields_have_chinese_help():
    fields = {field.path: field for field in editable_account_fields(fake_daily_task)}
    assert fields["account.account_aliases"].read_only
    assert fields["tasks.Which to Farm"].label == "体力用途"
    assert fields["tasks.Which to Farm"].help_text

def test_sequence_delete_success_refreshes_and_failure_is_visible():
    tab = make_sequence_tab(service=service_that_raises("修订冲突"))
    tab.confirm_delete = lambda *_: True
    tab._delete()
    assert "修订冲突" in tab.status.text()
```

- [ ] **Step 2: Run tests and verify metadata/hub APIs are missing**

Run: `rtk .\.venv\Scripts\python.exe -m unittest tests.TestAccountSettingsTab`

Expected: FAIL on import/missing APIs.

- [ ] **Step 3: Implement metadata by adapting existing task configuration metadata**

Map known English keys to Chinese labels, then reuse `DailyTask.config_description` and `config_type` for help and editor types. Mark `profile_id`, `account_aliases`, login-name aliases, passwords, tokens, and credentials as identity/read-only. Generate switch, combo, multi-select, numeric, and line-edit widgets from metadata; preserve a collapsed advanced JSON editor for unknown non-sensitive fields.

- [ ] **Step 4: Add account delete controls and two confirmations**

First dialog confirms the selected short name. Second dialog lists affected sequences and runtime-state deletion. On confirmation, call exactly `editor.delete_profile`; on success select the next account and refresh. On failure retain the current draft and show a sanitized message.

- [ ] **Step 5: Fix every sequence mutating callback through one visible error boundary**

```python
def _run_action(self, label, callback):
    try:
        self.status.setText(f"{label}中…")
        result = callback()
        self.refresh()
        self.status.setText(f"{label}成功")
        return result
    except Exception as exc:
        self.status.setText(f"{label}失败：{sanitize_error(exc)}")
        return None
```

Route create/copy/rename/toggle/delete/reorder through it. For deletion, compare the Qt response to `QMessageBox.StandardButton.Yes`, then call `service.delete(item.sequence_id)` once. Preserve selection when the operation fails.

- [ ] **Step 6: Build the account hub and move maintenance actions into it**

Embed/reuse AccountConfigTab, SequenceManagementTab, and a data-maintenance panel containing import/export, verify/restore backup, old-sequence repair, and integrity review. Register only `AccountSettingsTab` in `MainWindow`.

- [ ] **Step 7: Run account editor, deletion, sequence, GUI, and startup tests**

Run: `rtk .\.venv\Scripts\python.exe -m unittest tests.TestAccountSettingsTab tests.TestAccountConfigEditor tests.TestAccountDeletion tests.TestSequenceRepository tests.TestAccountManagementTabs tests.TestMainWindowStartup`

Expected: PASS.

- [ ] **Step 8: Commit account settings UI**

```powershell
rtk git add -- src/gui/AccountSettingsTab.py src/account_field_metadata.py src/gui/AccountConfigTab.py src/gui/SequenceManagementTab.py custom_ok/ok/gui/MainWindow.py tests/TestAccountSettingsTab.py tests/TestAccountConfigEditor.py tests/TestSequenceRepository.py
rtk git commit -m "feat: simplify account and sequence management"
```

---

### Task 5: Integrated Tasks, Activities, and Tests Pages

**Files:**
- Create: `src/gui/TaskHubTab.py`
- Create: `src/gui/ActivityHubTab.py`
- Create: `src/gui/TestHubTab.py`
- Modify: `custom_ok/ok/gui/MainWindow.py`
- Modify: `src/task/EventTask.py`
- Modify: `src/task/TestAccountSwitchTask.py`
- Create: `tests/TestTaskNavigationClassification.py`
- Modify: `tests/TestAccountSwitch.py`

**Interfaces:**
- Consumes: `classify_task`, existing `OneTimeTaskTab` task cards/log panel, executor task list.
- Produces: three integrated hub tabs; task metadata `navigation_section` and `activity_category`.

- [ ] **Step 1: Write failing classification tests**

```python
def test_event_and_test_classification():
    event = object.__new__(EventTask)
    switch_test = object.__new__(TestAccountSwitchTask)
    assert EventTask.activity_category == "常驻活动"
    assert classify_task(event) == ACTIVITIES
    assert classify_task(switch_test) == TESTS

def test_account_switch_copy_names_production_owner():
    task = object.__new__(TestAccountSwitchTask)
    assert "多账号每日任务" in task.name
```

- [ ] **Step 2: Run classification tests and confirm metadata is absent**

Run: `rtk .\.venv\Scripts\python.exe -m unittest tests.TestTaskNavigationClassification tests.TestAccountSwitch`

Expected: FAIL on missing category/name contract.

- [ ] **Step 3: Implement task hub**

Display all visible tasks classified as `TASKS` in one page, reusing existing task cards and the persistent run-log panel. Do not create separate left navigation for individual task groups.

- [ ] **Step 4: Implement activity hub**

Display two internal sections/tabs: 限时活动 and 常驻活动. Set:

```python
class EventTask(...):
    navigation_section = "activities"
    activity_category = "常驻活动"
```

No new limited-time task is added.

- [ ] **Step 5: Implement test hub and re-audit switch reuse**

Set `TestAccountSwitchTask.navigation_section = "tests"`, rename it to `多账号每日任务：账号切换链路测试`, and update its description. Keep calls to `mat.create_run_snapshot`, `mat._snapshot_profile_names`, and `mat._select_and_login_sequence`; tests must assert there is no independent switch/logout implementation.

- [ ] **Step 6: Register the three hubs and run classification/switch/startup tests**

Run: `rtk .\.venv\Scripts\python.exe -m unittest tests.TestTaskNavigationClassification tests.TestAccountSwitch tests.TestMultiAccountDailyTask tests.TestMainWindowStartup`

Expected: PASS.

- [ ] **Step 7: Commit task/activity/test hubs**

```powershell
rtk git add -- src/gui/TaskHubTab.py src/gui/ActivityHubTab.py src/gui/TestHubTab.py custom_ok/ok/gui/MainWindow.py src/task/EventTask.py src/task/TestAccountSwitchTask.py tests/TestTaskNavigationClassification.py tests/TestAccountSwitch.py
rtk git commit -m "feat: consolidate tasks activities and tests"
```

---

### Task 6: Navigation Integration and Real UI Smoke Verification

**Files:**
- Modify: `custom_ok/ok/gui/MainWindow.py`
- Modify: `tests/TestMainWindowStartup.py`
- Create: `tests/TestFiveSectionMainWindow.py`

**Interfaces:**
- Consumes: all five hub classes.
- Produces: final `MainWindow` navigation order and route ownership.

- [ ] **Step 1: Add a fake-window integration test**

```python
def test_main_window_adds_only_five_scroll_routes_and_program_bottom_routes():
    window = build_window_with_fake_navigation()
    assert window.scroll_route_titles == ["通用设置", "账号设置", "任务", "活动", "测试功能"]
    assert "计划任务" not in window.all_route_titles
    assert "实时触发" not in window.all_route_titles
    assert "游戏快捷键" not in window.all_route_titles
    assert {"程序设置", "重启程序", "关于"} <= set(window.bottom_route_titles)
```

- [ ] **Step 2: Run the test before final wiring**

Run: `rtk .\.venv\Scripts\python.exe -m unittest tests.TestFiveSectionMainWindow`

Expected: FAIL until all old registrations are removed.

- [ ] **Step 3: Complete final wiring and remove obsolete route creation**

Instantiate one GeneralSettingsTab, AccountSettingsTab, TaskHubTab, ActivityHubTab, and TestHubTab. Preserve notification behavior inside general settings. Keep debug-only bottom tools only when debug mode is enabled. Continue invoking startup integrity review and automatic backup regardless of current tab.

- [ ] **Step 4: Launch an offscreen GUI smoke check**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
rtk .\.venv\Scripts\python.exe -m unittest tests.TestFiveSectionMainWindow tests.TestMainWindowStartup
```

Expected: PASS without constructing extra navigation routes.

- [ ] **Step 5: Commit final navigation integration**

```powershell
rtk git add -- custom_ok/ok/gui/MainWindow.py tests/TestMainWindowStartup.py tests/TestFiveSectionMainWindow.py
rtk git commit -m "fix: finalize five-section main navigation"
```

---

### Task 7: Version, Handoff, Regression, and Release

**Files:**
- Modify: `config.py`
- Modify: `custom_ok/ok/gui/about/AboutTab.py`
- Modify: `更新日志.md`
- Create: `交接/五栏导航与账号删除交接日志_2026-08-25.md`
- Modify: `docs/references/pc-account-configuration-and-sequences.md`

**Interfaces:**
- Documents final navigation ownership, deletion recovery, sequence bug root cause, test evidence, and known limitations.

- [ ] **Step 1: Update version and user-facing notes**

Set `config.py` to `1.14.00` if `v1.14.00` remains unused. Add matching About and changelog text covering five hubs, account cascade deletion, visible sequence deletion errors, structured Chinese editing, activity migration, test labeling, and hidden schedule.

- [ ] **Step 2: Write handoff and update references**

Record exact changed files, authoritative data, backup/rollback sequence, migration from old routes, manual smoke steps, focused/full test results, and any unrelated dirty files intentionally excluded.

- [ ] **Step 3: Compile changed Python files**

Run:

```powershell
rtk .\.venv\Scripts\python.exe -m py_compile config.py custom_ok\ok\gui\MainWindow.py custom_ok\ok\gui\settings\SettingTab.py custom_ok\ok\gui\about\AboutTab.py src\account_repository.py src\sequence_repository.py src\account_config_editor.py src\account_field_metadata.py src\gui\navigation_sections.py src\gui\GeneralSettingsTab.py src\gui\AccountSettingsTab.py src\gui\AccountConfigTab.py src\gui\SequenceManagementTab.py src\gui\TaskHubTab.py src\gui\ActivityHubTab.py src\gui\TestHubTab.py src\task\EventTask.py src\task\TestAccountSwitchTask.py
```

Expected: exit 0.

- [ ] **Step 4: Run focused regression**

Run:

```powershell
rtk .\.venv\Scripts\python.exe -m unittest `
  tests.TestNavigationSections tests.TestGeneralSettingsTab tests.TestAccountDeletion `
  tests.TestAccountSettingsTab tests.TestAccountConfigEditor tests.TestSequenceRepository `
  tests.TestTaskNavigationClassification tests.TestFiveSectionMainWindow `
  tests.TestAccountSwitch tests.TestMultiAccountDailyTask tests.TestConfigIntegrity `
  tests.TestAccountConfigBundle tests.TestMainWindowStartup
```

Expected: PASS.

- [ ] **Step 5: Run repository suite and classify only known baseline image failures**

Run: `rtk .\.venv\Scripts\python.exe -m unittest discover -s tests -p "Test*.py"`

Expected: all non-image tests pass; if the existing 29 `TaskTestCase.set_image → FinishedException` errors remain unchanged, document them. Any new failure blocks release.

- [ ] **Step 6: Review release scope**

Run:

```powershell
rtk git diff --check
rtk git status --short
rtk rg -n -i "android|mumu|\badb\b|combat agent|device_id" src/gui src/account_repository.py src/sequence_repository.py src/account_config_editor.py src/account_field_metadata.py custom_ok/ok/gui/MainWindow.py custom_ok/ok/gui/settings/SettingTab.py
rtk git tag -l v1.14.00
rtk git ls-remote --tags origin refs/tags/v1.14.00
```

Expected: diff check clean; restricted terms only appear in explicit “not imported” documentation; tag absent locally/remotely.

- [ ] **Step 7: Commit, tag, and push only verified task files**

```powershell
rtk git add -- config.py custom_ok/ok/gui/MainWindow.py custom_ok/ok/gui/settings/SettingTab.py custom_ok/ok/gui/about/AboutTab.py src/account_repository.py src/sequence_repository.py src/account_config_editor.py src/account_field_metadata.py src/gui/navigation_sections.py src/gui/GeneralSettingsTab.py src/gui/AccountSettingsTab.py src/gui/AccountConfigTab.py src/gui/SequenceManagementTab.py src/gui/TaskHubTab.py src/gui/ActivityHubTab.py src/gui/TestHubTab.py src/task/EventTask.py src/task/TestAccountSwitchTask.py tests/TestNavigationSections.py tests/TestGeneralSettingsTab.py tests/TestAccountDeletion.py tests/TestAccountSettingsTab.py tests/TestAccountConfigEditor.py tests/TestSequenceRepository.py tests/TestTaskNavigationClassification.py tests/TestAccountSwitch.py tests/TestFiveSectionMainWindow.py tests/TestMainWindowStartup.py 更新日志.md 交接/五栏导航与账号删除交接日志_2026-08-25.md docs/references/pc-account-configuration-and-sequences.md
rtk git commit -m "feat: reorganize UI and account management; v1.14.00"
rtk git tag -a v1.14.00 -m "v1.14.00"
rtk git push origin HEAD v1.14.00
```

Verify remote branch and annotated tag before reporting completion. Never stage unrelated existing bundle experiments, launcher edits, incident folders, or `.superpowers/` design-session files.
