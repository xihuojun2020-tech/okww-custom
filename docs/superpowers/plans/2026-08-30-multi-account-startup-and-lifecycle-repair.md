# Multi-Account Startup and Lifecycle Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复多账号每日任务在游戏世界内误判为登录界面、失败后残留“任务已经在运行”锁的问题，并用打包版完成 A3 → A4 实机回归。

**Architecture:** 保留现有序列快照、账号身份匹配和正式切换链路。把“确保处于登录界面”的兜底放在共享生产入口 `switch_to_account()`：只有账号下拉框不可见且 `in_team()[0]` 明确为真时才退登；把运行协调器的成功、停止、失败收尾统一放在 `run()` 的异常边界，保证任何出口都会结束本轮状态。

**Tech Stack:** Python 3.12、`unittest`、ok-script 任务框架、Windows WGC/PostMessage、PySide6、Git/pyappify 打包更新。

**Spec:** `docs/superpowers/plans/2026-08-30-multi-account-startup-and-lifecycle-repair.md#已确认问题与设计`

## Global Constraints

- 只修改 PC 端多账号每日任务及其直接测试、版本和文档；不得纳入或回滚当前未提交的 MuMu/Android 文件。
- 账号序列继续由 `AccountRepository`/`SequenceSnapshotService` 提供不可变快照；不得改回从 UI 缓存直接执行。
- A3/A4 必须使用各自独立账号配置；不得修改打包版 `working/configs/account_master_config.json` 的账号内容。
- 手机号掩码是账号切换首要识别依据，备用登录名是次级依据；本次不启用游戏特征码校验。
- `TestAccountSwitchTask` 必须继续复用 `MultiAccountDailyTask.switch_to_account()`，不得增加第二套账号切换实现。
- 所有 Python 命令使用 `E:\AI work\ok-wuthering-waves-master\.venv\Scripts\python.exe`；若缺少测试依赖，记录环境阻塞，不得静默改用全局 Python。
- 代码变更版本从 `1.19.11` 升为 `1.19.12`，同步 About 页面、更新日志、交接日志和参考文献。
- 验证通过后提交、创建 annotated tag `v1.19.12`，推送 `master` 和标签；打包版必须显示 `v1.19.12` 后才能实机验收。

---

## 已确认问题与设计

### 现场证据

- 打包版已运行 `v1.19.11`。
- 2026-08-30 17:46 首次启动多账号每日任务时，证据截图仍显示角色处于游戏世界内且队伍 HUD 可见。
- `_run_inner()` 的 `is_main(esc=False)` 返回假值，程序进入“已经在登录界面”的分支。
- `switch_to_account()` 随后等待账号下拉框 120 秒，最终抛出 `Timed out waiting for the login screen`。
- 首次异常没有调用 `TaskRunCoordinator.fail()` 或 `request_stop()`；17:51 后再次点击均抛出 `RuntimeError: 任务已经在运行`。
- 权威序列包含 A4、A3；配置的“当前执行账号”为 A3，现有 `_next_target_account()` 会将本轮顺序旋转为 A3 → A4，这部分逻辑不需要改写。

### 修复边界

1. `switch_to_account()` 在等待登录界面前执行一次只读状态检查：
   - 已检测到账号下拉框：直接沿用现有登录流程；
   - 未检测到账号下拉框且 `in_team()[0] is True`：调用现有 `_switch_to_login()`；
   - 无法证明在队伍中：不发送 ESC 或点击，继续沿用现有稳定等待与超时证据流程。
2. `run()` 在 `_run_inner()` 外统一收尾：
   - 正常结束：`request_stop()`，最终状态为 `STOPPED`；
   - `TaskDisabledException`：`request_stop()` 后原样抛出；
   - 其他异常：`fail(str(error))` 后原样抛出，最终状态为 `FAILED`；
   - 下一次运行允许从 `STOPPED` 或 `FAILED` 重新 `start()`。
3. 不新增登录状态机，不修改账号 OCR、账号点击坐标、序列仓库和每日任务业务流程。

---

### Task 1: 锁定游戏世界启动时的失败回归

**Files:**
- Modify: `tests/TestMultiAccountDailyTask.py`
- Test: `tests/TestMultiAccountDailyTask.py`

**Interfaces:**
- Consumes: `MultiAccountDailyTask.switch_to_account(profile_name: str, *, max_retries: int = 5) -> str`
- Produces: 两个回归测试，证明只有明确在游戏世界内时才执行退登，登录界面不重复退登。

- [ ] **Step 1: 写“游戏世界内启动”失败测试**

在 `TestMultiAccountDailyTask` 中增加最小替身。让账号下拉框第一次不存在、`in_team()` 返回 `(True, 0, 3)`，并记录 `_switch_to_login()` 和 `_wait_login_screen_stable()` 的调用顺序：

```python
def test_switch_to_account_logs_out_when_world_team_is_visible(self):
    events = []

    class FakeTask:
        switch_to_account = MultiAccountDailyTask.switch_to_account
        do_find_account_drop_down = lambda self: None
        in_team = lambda self: (True, 0, 3)
        _switch_to_login = lambda self: events.append("logout") or True
        _wait_login_screen_stable = lambda self, **kwargs: events.append("wait_login")
        _select_account_with_retry = lambda self, *args, **kwargs: None
        _click_login_for_target = lambda self, *args, **kwargs: None
        ensure_main = lambda self, **kwargs: None
        sleep = lambda self, *_args: None
        _guard_account_transition = lambda self: None
        _begin_account_switch_evidence = lambda self, *_args: None
        _evidence_stage = lambda self, *_args: None
        _finish_account_switch_evidence = lambda self, *_args, **_kwargs: None
        log_info = lambda self, *_args, **_kwargs: None
        executor = None

    self.assertEqual(FakeTask().switch_to_account("A3"), "A3")
    self.assertEqual(events[:2], ["logout", "wait_login"])
```

- [ ] **Step 2: 写“已经位于登录界面”保护测试**

让 `do_find_account_drop_down()` 返回对象并验证 `_switch_to_login()` 没有被调用：

```python
def test_switch_to_account_does_not_logout_from_login_screen(self):
    events = []

    class FakeTask:
        switch_to_account = MultiAccountDailyTask.switch_to_account
        do_find_account_drop_down = lambda self: object()
        in_team = lambda self: (_ for _ in ()).throw(AssertionError("must not probe team"))
        _switch_to_login = lambda self: events.append("logout")
        _wait_login_screen_stable = lambda self, **kwargs: events.append("wait_login")
        _select_account_with_retry = lambda self, *args, **kwargs: None
        _click_login_for_target = lambda self, *args, **kwargs: None
        ensure_main = lambda self, **kwargs: None
        sleep = lambda self, *_args: None
        _guard_account_transition = lambda self: None
        _begin_account_switch_evidence = lambda self, *_args: None
        _evidence_stage = lambda self, *_args: None
        _finish_account_switch_evidence = lambda self, *_args, **_kwargs: None
        log_info = lambda self, *_args, **_kwargs: None
        executor = None

    FakeTask().switch_to_account("A3")
    self.assertEqual(events, ["wait_login"])
```

- [ ] **Step 3: 运行测试并确认当前代码失败**

Run:

```powershell
& 'E:\AI work\ok-wuthering-waves-master\.venv\Scripts\python.exe' -m unittest `
  tests.TestMultiAccountDailyTask.TestMultiAccountDailyTask.test_switch_to_account_logs_out_when_world_team_is_visible `
  tests.TestMultiAccountDailyTask.TestMultiAccountDailyTask.test_switch_to_account_does_not_logout_from_login_screen -v
```

Expected: 第一个测试失败，事件中缺少 `logout`；第二个测试建立“不重复退登”的保护基线。

- [ ] **Step 4: 提交测试基线**

```powershell
git add tests/TestMultiAccountDailyTask.py
git commit -m "test: cover multi-account startup from game world"
```

---

### Task 2: 在共享账号切换入口补登录界面兜底

**Files:**
- Modify: `src/task/MultiAccountDailyTask.py:923`
- Test: `tests/TestMultiAccountDailyTask.py`

**Interfaces:**
- Consumes: `do_find_account_drop_down() -> Box | None`、`in_team() -> tuple[bool, int, int]`、`_switch_to_login() -> bool`
- Produces: `switch_to_account()` 在明确检测到游戏内队伍时先安全退登，之后仍复用原有等待、选择、核验、登录和 `ensure_main()` 链路。

- [ ] **Step 1: 加入最小兜底逻辑**

在禁用 `MouseResetTask` 后、`_evidence_stage('wait_login_screen')` 前加入：

```python
if self.do_find_account_drop_down() is None:
    try:
        in_team = bool(self.in_team()[0])
    except TaskDisabledException:
        raise
    except Exception:
        in_team = False
    if in_team:
        self.log_info('检测到仍在游戏世界内，先退登再执行账号切换')
        self._evidence_stage('logout_from_world')
        self._switch_to_login()
```

约束：`in_team` 无法确认时不得发送 ESC；继续由 `_wait_login_screen_stable()` 超时并保存证据。

- [ ] **Step 2: 运行两个新测试**

Run: 使用 Task 1 Step 3 的同一命令。

Expected: PASS，事件顺序为 `logout` → `wait_login`；已在登录页时仅出现 `wait_login`。

- [ ] **Step 3: 运行现有退登与登录测试**

```powershell
& 'E:\AI work\ok-wuthering-waves-master\.venv\Scripts\python.exe' -m unittest `
  tests.TestMultiAccountDailyTask `
  tests.TestAccountSwitchEvidence `
  tests.TestAccountRuntimeIntegration -v
```

Expected: PASS；现有确认框重试、对话框 OCR、掩码手机号优先、备用登录名、点击证据保存行为不变。

- [ ] **Step 4: 提交共享入口修复**

```powershell
git add src/task/MultiAccountDailyTask.py tests/TestMultiAccountDailyTask.py
git commit -m "fix: recover account switching from game world"
```

---

### Task 3: 保证运行协调器在所有出口释放

**Files:**
- Modify: `src/task/MultiAccountDailyTask.py:646`
- Modify: `tests/TestMultiAccountDailyTask.py`
- Test: `tests/TestRuntimeServices.py`

**Interfaces:**
- Consumes: `TaskRunCoordinator.start(snapshot)`、`request_stop()`、`fail(error: str)`
- Produces: `MultiAccountDailyTask.run()` 的正常、停止和异常生命周期；失败后同一任务对象可立即重跑。

测试文件补充以下导入：

```python
from types import SimpleNamespace

from src.runtime.task_run_coordinator import TaskRunCoordinator, TaskRunState
from src.task.WWOneTimeTask import WWOneTimeTask
```

- [ ] **Step 1: 写失败后可重跑测试**

构造最小任务，使第一次 `_run_inner()` 抛出 `RuntimeError('login timeout')`，检查协调器进入 `FAILED`；第二次创建快照必须允许 `start()`，不得抛出“任务已经在运行”：

```python
def test_run_marks_coordinator_failed_and_allows_retry(self):
    task = MultiAccountDailyTask.__new__(MultiAccountDailyTask)
    task.run_coordinator = TaskRunCoordinator()
    task._account_refresh_pending = False
    task.integrity_service = None
    task.done_set = set()
    task.all_accounts = set()
    task._sync_local_to_sequences = lambda: None
    task.get_task_by_class = lambda *_args: None
    task.log_error = task.log_info = lambda *_args, **_kwargs: None
    task._run_inner = lambda: (_ for _ in ()).throw(RuntimeError("login timeout"))

    with patch.object(WWOneTimeTask, "run", return_value=None):
        with self.assertRaisesRegex(RuntimeError, "login timeout"):
            task.run()
    self.assertEqual(task.run_coordinator.state, TaskRunState.FAILED)

    snapshot = SimpleNamespace(profile_ids=("a3",), sequence_id="序列1", revision="r", run_id="retry")
    task.run_coordinator.start(snapshot)
    self.assertEqual(task.run_coordinator.state, TaskRunState.RUNNING)
```

- [ ] **Step 2: 写手动停止与正常结束测试**

分别让 `_run_inner()` 抛出 `TaskDisabledException` 和正常返回，验证最终均为 `STOPPED`，并且原异常继续向上传播：

```python
def test_run_marks_coordinator_stopped_on_disable(self):
    task = MultiAccountDailyTask.__new__(MultiAccountDailyTask)
    task.run_coordinator = TaskRunCoordinator()
    snapshot = SimpleNamespace(profile_ids=("a3",), sequence_id="序列1", revision="r", run_id="stop")
    task.run_coordinator.start(snapshot)
    task._account_refresh_pending = False
    task.integrity_service = None
    task.done_set = set()
    task.all_accounts = set()
    task._sync_local_to_sequences = lambda: None
    task.get_task_by_class = lambda *_args: None
    task.log_error = task.log_info = lambda *_args, **_kwargs: None

    def stop_run():
        raise TaskDisabledException()

    task._run_inner = stop_run
    with patch.object(WWOneTimeTask, "run", return_value=None):
        with self.assertRaises(TaskDisabledException):
            task.run()
    self.assertEqual(task.run_coordinator.state, TaskRunState.STOPPED)

def test_run_marks_coordinator_stopped_after_success(self):
    task = MultiAccountDailyTask.__new__(MultiAccountDailyTask)
    task.run_coordinator = TaskRunCoordinator()
    snapshot = SimpleNamespace(profile_ids=("a3",), sequence_id="序列1", revision="r", run_id="success")
    task.run_coordinator.start(snapshot)
    task._account_refresh_pending = False
    task.integrity_service = None
    task.done_set = set()
    task.all_accounts = set()
    task._sync_local_to_sequences = lambda: None
    task.get_task_by_class = lambda *_args: None
    task.log_error = task.log_info = lambda *_args, **_kwargs: None
    task._run_inner = lambda: None

    with patch.object(WWOneTimeTask, "run", return_value=None):
        task.run()
    self.assertEqual(task.run_coordinator.state, TaskRunState.STOPPED)
```

- [ ] **Step 3: 运行新生命周期测试并确认失败**

```powershell
& 'E:\AI work\ok-wuthering-waves-master\.venv\Scripts\python.exe' -m unittest `
  tests.TestMultiAccountDailyTask.TestMultiAccountDailyTask.test_run_marks_coordinator_failed_and_allows_retry `
  tests.TestMultiAccountDailyTask.TestMultiAccountDailyTask.test_run_marks_coordinator_stopped_on_disable `
  tests.TestMultiAccountDailyTask.TestMultiAccountDailyTask.test_run_marks_coordinator_stopped_after_success -v
```

Expected: 当前代码下至少失败状态和停止状态断言失败。

- [ ] **Step 4: 在 `run()` 的单一边界实现收尾**

将当前空的 `finally: pass` 改为明确的异常边界；不要在每个子流程重复清理：

```python
try:
    if daily_task is not None:
        override = getattr(daily_task, 'runtime_config_override', None)
        context = override(LOGOUT_AFTER_DAILY_KEY, False) if callable(override) else nullcontext()
        with context:
            self._run_inner()
    else:
        self._run_inner()
except TaskDisabledException:
    self.run_coordinator.request_stop()
    raise
except Exception as error:
    self.run_coordinator.fail(str(error))
    raise
else:
    self.run_coordinator.request_stop()
```

约束：不得吞掉异常；UI 仍显示原始失败原因，协调器只负责状态与重跑许可。

- [ ] **Step 5: 运行生命周期和运行服务测试**

```powershell
& 'E:\AI work\ok-wuthering-waves-master\.venv\Scripts\python.exe' -m unittest `
  tests.TestMultiAccountDailyTask `
  tests.TestRuntimeServices -v
```

Expected: PASS；快照内容在停止后保持不可变。

- [ ] **Step 6: 提交生命周期修复**

```powershell
git add src/task/MultiAccountDailyTask.py tests/TestMultiAccountDailyTask.py tests/TestRuntimeServices.py
git commit -m "fix: release multi-account run state on every exit"
```

---

### Task 4: 验证 A3 → A4 序列顺序与配置隔离

**Files:**
- Modify: `tests/TestMultiAccountDailyTask.py`
- Test: `tests/TestAccountRepository.py`
- Test: `tests/TestAccountRuntimeIntegration.py`

**Interfaces:**
- Consumes: `_next_target_account()`、`create_run_snapshot()`、`_require_daily_profile()`、`DailyTask.bind_verified_profile(profile_id)`
- Produces: A3 起点旋转顺序和逐账号配置绑定的回归保证。

- [ ] **Step 1: 增加乱序序列的起点旋转测试**

权威序列按 `[A4, A3]` 返回、`CURRENT_ACCOUNT` 为 A3 时，验证连续选择为 A3 后 A4：

```python
def test_current_account_rotates_a4_a3_sequence_to_a3_then_a4(self):
    task = MultiAccountDailyTask.__new__(MultiAccountDailyTask)
    task.config = {CURRENT_ACCOUNT: "A3"}
    task.get_sequence_accounts = lambda: ["A4", "A3"]
    task.done_set = set()
    task._same_account = lambda left, right: left == right
    task._is_done = lambda account: account in task.done_set

    self.assertEqual(task._next_target_account(), "A3")
    task.done_set.add("A3")
    self.assertEqual(task._next_target_account(), "A4")
```

- [ ] **Step 2: 增加逐账号配置绑定断言**

复用 `TestAccountRuntimeIntegration` 的仓库替身，创建 A3/A4 不同 `task_config`，依次调用 `_require_daily_profile()`，断言 DailyTask 每次收到对应 profile UUID，且 A3 配置字典未被 A4 写入污染。

- [ ] **Step 3: 运行账号、序列和运行时测试**

```powershell
& 'E:\AI work\ok-wuthering-waves-master\.venv\Scripts\python.exe' -m unittest `
  tests.TestMultiAccountDailyTask `
  tests.TestAccountRepository `
  tests.TestAccountRuntimeIntegration `
  tests.TestSequenceRepository -v
```

Expected: PASS；顺序为 A3 → A4，每次按不可变 UUID 快照绑定独立配置。

- [ ] **Step 4: 提交序列与配置隔离回归**

```powershell
git add tests/TestMultiAccountDailyTask.py tests/TestAccountRuntimeIntegration.py
git commit -m "test: lock A3 A4 multi-account execution order"
```

---

### Task 5: 检查配置自动备份失败但不扩大本次修复

**Files:**
- Inspect: `src/config_backup.py`
- Test: `tests/TestConfigBackup.py`
- Inspect: `E:\game\okww owener\data\apps\okww-custom\working\configs_backup`

**Interfaces:**
- Consumes: `ConfigBackupService.create_daily_snapshot()` 和备份验证结果
- Produces: 一份明确结论：预存问题、环境问题或本次版本引入的回归。

- [ ] **Step 1: 在打包版账号配置只读状态下复现备份验证**

使用项目现有备份测试或只读验证入口；不得删除备份、事务目录或账号配置。

- [ ] **Step 2: 检查失败原因是否与本次修改相关**

核对源文件、清单 SHA-256、目标快照和可用空间。输出必须明确到具体文件与验证项，日志中不得记录完整手机号、备用登录名或游戏特征码。

- [ ] **Step 3: 按结论处理**

- 若是本次代码回归：在 `src/config_backup.py` 做最小修复并补 `tests/TestConfigBackup.py`；代码变更仍归入 `1.19.12`。
- 若是旧损坏快照或运行环境问题：记录为已知问题，不改变多账号代码，不以删除历史备份作为修复。

- [ ] **Step 4: 运行备份测试**

```powershell
& 'E:\AI work\ok-wuthering-waves-master\.venv\Scripts\python.exe' -m unittest tests.TestConfigBackup -v
```

Expected: PASS，或得到一个与多账号修复无关且可复现的明确环境阻塞说明。

---

### Task 6: 全量确定性回归与静态检查

**Files:**
- Test: `tests/TestMultiAccountDailyTask.py`
- Test: `tests/TestAccountSwitchEvidence.py`
- Test: `tests/TestAccountRuntimeIntegration.py`
- Test: `tests/TestRuntimeServices.py`
- Test: `tests/TestScheduleSupport.py`
- Test: `tests/TestConfigBackup.py`

**Interfaces:**
- Consumes: Tasks 1–5 的所有行为
- Produces: 可发布的确定性测试证据。

- [ ] **Step 1: 编译修改范围**

```powershell
& 'E:\AI work\ok-wuthering-waves-master\.venv\Scripts\python.exe' -m compileall -q src tests
```

Expected: exit code 0。

- [ ] **Step 2: 运行多账号确定性测试组**

```powershell
& 'E:\AI work\ok-wuthering-waves-master\.venv\Scripts\python.exe' -m unittest `
  tests.TestMultiAccountDailyTask `
  tests.TestAccountSwitchEvidence `
  tests.TestAccountRuntimeIntegration `
  tests.TestRuntimeServices `
  tests.TestScheduleSupport `
  tests.TestConfigBackup -v
```

Expected: 全部 PASS；任何新增失败阻止发布。

- [ ] **Step 3: 运行仓库提供的确定性测试入口**

```powershell
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1 -Deterministic
```

Expected: 确定性组 PASS；已有图像基线测试单独记录，不得把新失败归为既有问题。

- [ ] **Step 4: 检查差异边界**

```powershell
git diff --check
git status --short
git diff -- src/task/MultiAccountDailyTask.py tests/TestMultiAccountDailyTask.py tests/TestRuntimeServices.py
```

Expected: 无空白错误；`src/android/nemu.py`、`src/android/preflight.py`、`android/agent-app/` 及 Android 计划文件仍保持用户原有未提交状态，不进入本次提交。

---

### Task 7: 同步版本、更新日志、交接和参考文献

**Files:**
- Modify: `config.py:17`
- Modify: `custom_ok/ok/gui/about/AboutTab.py`
- Modify: `更新日志.md`
- Modify: `交接/综合优化实施交接日志_2026-08-26.md`
- Modify: `docs/references/pc-account-configuration-and-sequences.md`
- Test: `tests/TestReleaseReadiness.py`

**Interfaces:**
- Consumes: 已验证修复与测试结果
- Produces: 所有产品版本文本一致为 `1.19.12`。

- [ ] **Step 1: 增加发布一致性测试**

确保 `config.py`、About、更新日志和交接日志均包含 `1.19.12`。

- [ ] **Step 2: 更新版本号与用户可见说明**

将 `config.py` 设置为：

```python
version = "1.19.12"
```

About 与更新日志明确写入：

- 游戏世界内启动时，队伍 HUD 作为安全兜底，仅在明确在队伍中时先退登；
- 失败、停止和正常完成都会释放运行协调器；
- A3/A4 序列快照和独立配置行为不变；
- 不修改账号配置数据。

- [ ] **Step 3: 更新交接与参考文献**

记录现场日志时间、证据目录、根因、修改文件、测试命令、打包版验收步骤、回滚方式 `git revert <release-commit>`，以及打包版从 `v1.19.11` 升到 `v1.19.12`。

- [ ] **Step 4: 运行发布一致性测试**

```powershell
& 'E:\AI work\ok-wuthering-waves-master\.venv\Scripts\python.exe' -m unittest tests.TestReleaseReadiness -v
```

Expected: PASS。

- [ ] **Step 5: 提交版本与文档**

```powershell
git add config.py custom_ok/ok/gui/about/AboutTab.py 更新日志.md `
  交接/综合优化实施交接日志_2026-08-26.md `
  docs/references/pc-account-configuration-and-sequences.md tests/TestReleaseReadiness.py
git commit -m "release: prepare multi-account recovery v1.19.12"
```

---

### Task 8: 发布并升级打包版

**Files:**
- Publish: Git branch `master`
- Create: annotated tag `v1.19.12`
- Update target: `E:\game\okww owener\data\apps\okww-custom\repo`
- Update target: `E:\game\okww owener\data\apps\okww-custom\working`
- Preserve: `E:\game\okww owener\data\apps\okww-custom\working\configs`

**Interfaces:**
- Consumes: 已通过 Task 6–7 验证的提交
- Produces: 打包版 `app.json.current_version == "v1.19.12"` 且账号配置未改变。

- [ ] **Step 1: 发布前记录配置哈希**

对打包版以下文件计算 SHA-256 并保存到临时验收记录，不输出文件内容：

- `configs/account_master_config.json`
- `configs/account_runtime_state.json`
- `configs/MultiAccountDailyTask.json`
- `configs/DailyTask.json`

- [ ] **Step 2: 创建标签并推送**

```powershell
git tag -a v1.19.12 -m "Release v1.19.12"
git push origin master
git push origin v1.19.12
```

Expected: 分支和标签均推送成功；不得移动任何现有标签。

- [ ] **Step 3: 使用现有 pyappify 自动更新打包版**

关闭正在运行的 OK-WW 任务，通过打包版更新器升级。不得手工覆盖 `working/configs`。

- [ ] **Step 4: 核对打包版版本与配置完整性**

确认：

```text
app.json.current_version = v1.19.12
working/config.py version = 1.19.12
```

重新计算 Task 8 Step 1 的四个配置哈希，Expected: 与升级前一致。

---

### Task 9: A3/A4 打包版实机验收

**Files:**
- Observe: `E:\game\okww owener\data\apps\okww-custom\working\logs\ok-script.log`
- Observe: `E:\game\okww owener\data\apps\okww-custom\working\screenshots\account_switch_failures`
- Observe: `E:\game\okww owener\data\apps\okww-custom\working\configs\multi_account_progress.json`

**Interfaces:**
- Consumes: 打包版 `v1.19.12`、序列1、当前执行账号 A3
- Produces: 游戏世界启动、失败恢复、A3 → A4 连续任务的实机证据。

- [ ] **Step 1: 准备安全起点**

让游戏停留在与失败截图相同类型的可恢复世界场景，角色可见且队伍 HUD 可见；关闭可能抢占 F9 的程序。确认多账号任务选择序列1、当前执行账号 A3。

- [ ] **Step 2: 验证游戏世界启动兜底**

启动一次多账号每日任务。Expected 日志顺序：

```text
检测到仍在游戏世界内，先退登再执行账号切换
Switching back to login screen
已在登录界面 / 已通过登录对话框窗口识别到登录界面
```

不得再次在游戏世界画面等待账号下拉框 120 秒。

- [ ] **Step 3: 验证 A3 执行**

确认登录目标是 A3，身份依据与 A3 配置唯一匹配；DailyTask 绑定 A3 的 UUID 和独立任务配置。完成后写入今日进度并退回登录界面。

- [ ] **Step 4: 验证 A4 执行**

确认下一目标是 A4；不得回到 A1/A2，也不得沿用 A3 的体力用途、凝素领域或周常设置。完成后写入 A4 今日进度。

- [ ] **Step 5: 验证失败后立即重跑**

在安全阶段主动停止一次任务，或使用测试替身触发一次可恢复失败。随后立即再次点击多账号每日任务。

Expected:

- 不出现 `RuntimeError: 任务已经在运行`；
- 停止后协调器状态为 `STOPPED`，异常后为 `FAILED`；
- 新一轮能够创建新的 `run_id` 和序列快照。

- [ ] **Step 6: 审查最终日志**

检查没有以下错误：

```text
Timed out waiting for the login screen   # 游戏世界误判导致
任务已经在运行                           # 前一轮已结束后
绑定到错误账号方案
```

账号日志只保留掩码身份或短名，不输出完整手机号、凭据和游戏特征码。

- [ ] **Step 7: 写入最终交接结果**

将实机结果、开始/完成时间、A3/A4 顺序、日志路径、是否发生重试、配置哈希一致性补充到交接日志。若任一验收项失败，不创建新的补丁标签覆盖 `v1.19.12`；修复后递增到下一个版本。
