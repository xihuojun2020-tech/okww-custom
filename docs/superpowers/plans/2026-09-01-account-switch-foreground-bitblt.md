# 账号切换前台 BitBlt 与精确入口点击实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 PC 账号切换在单次转换生命周期内使用主窗口前台 BitBlt 优先、WGC 后备和独立窗口 HWND BitBlt，并修复“点击连接”被泛化登录文本误识别后无法进入账号登录页的问题。

**Architecture:** `LoginFlowService` 持有一次账号转换的捕获会话；`MultiAccountDailyTask` 通过显式 `CaptureSample` 完成主窗口观察、独立窗口观察、OCR 坐标换算、SendInput 投递和状态确认。全局 WGC、普通任务 `PostMessage`、现有账号身份匹配与 `TestAccountSwitchTask` 生产复用关系保持不变。

**Tech Stack:** Python、现有 ok-script、pywin32、OpenCV、ForegroundBitBltCaptureMethod、WGC、Win32 SendInput、unittest、PowerShell。

**Spec:** `docs/superpowers/specs/2026-09-01-account-switch-foreground-bitblt-design.md`

## Global Constraints

- Python 命令必须使用 `.\.venv\Scripts\python.exe`。
- 不修改全局 `capture_method` 或 `interaction`，不调用 `DeviceManager.set_capture()`。
- 主窗口使用任务级前台 BitBlt 优先、WGC 后备；独立窗口和控件只使用各自 HWND BitBlt。
- 登录、退登和账号切换鼠标输入只使用经过校验的 `SendInput`，禁止 `PostMessage` 回退。
- 每次输入前重新观察、重新定位并重新确认目标 HWND/PID/前台；不复用旧截图坐标。
- `delivered` 与 `confirmed` 分开记录；无法确认目标账号时安全停止。
- `TestAccountSwitchTask` 必须继续调用生产 `LoginFlowService` 和生产任务方法。
- 自动测试不得调用真实 SendInput、启动或操作游戏；实机阶段只允许最新版 OKWW 自己操作游戏。
- 日志和报告只显示 A3/A4 短名，不输出账号身份细节。
- 保留且不得暂存现有 Android 脏改动与 Android 计划/规格文档。
- 当前候选 `1.22.02` 先推送备份分支；最终小修版本为 `1.22.03`。

---

### Task 1: 冻结并备份当前 1.22.02 候选源码

**Files:**
- Stage only the existing non-Android `1.22.02` candidate files.
- Do not stage: `src/android/nemu.py`, `src/android/preflight.py`, `android/agent-app/`, the 2026-08-26/27 Android plans/spec, generated ZIP files.
- Include this spec and plan only on the later implementation branch, not in the source snapshot commit.

**Interfaces:**
- Consumes the current verified candidate working tree.
- Produces remote branch `origin/codex/backup-v1.22.02-pre-switch-capture` containing a recoverable source snapshot without Android work.

- [ ] **Step 1: Record the exact dirty tree and remote**

```powershell
git status --short
git remote -v
git diff --check
```

Expected: `origin` is the OKWW repository; Android paths are visibly separate; `git diff --check` is clean.

- [ ] **Step 2: Re-run the current candidate’s non-game verification**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestMultiAccountDailyTask.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestFeatureSet.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestWin32LoginInput.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestDailyTaskStatus.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestReleaseReadiness.py
.\.venv\Scripts\python.exe -m compileall -q src custom_ok tests
.\.venv\Scripts\python.exe .\scripts\validate_release.py
```

Expected: all tests and compile checks pass; release validator prints `1.22.02`.

- [ ] **Step 3: Create the backup branch and stage an explicit allowlist**

```powershell
git switch -c codex/backup-v1.22.02-pre-switch-capture
git add -- assets/coco_annotations.json assets/images/logout_power_icon.png config.py custom_ok/ok/gui/about/AboutTab.py src/task/DailyTask.py src/task/MultiAccountDailyTask.py src/win32_login_input.py tests/TestDailyTaskStatus.py tests/TestFeatureSet.py tests/TestMultiAccountDailyTask.py tests/TestReleaseReadiness.py tests/TestWin32LoginInput.py 打包更新.py 更新日志.md
git diff --cached --name-only
```

Expected: the staged list contains only the allowlisted `1.22.02` candidate files; no Android or ZIP path appears.

- [ ] **Step 4: Commit and push the recoverable snapshot**

```powershell
git commit -m "chore: snapshot 1.22.02 account switch candidate"
git push -u origin codex/backup-v1.22.02-pre-switch-capture
git rev-parse HEAD
git ls-remote origin refs/heads/codex/backup-v1.22.02-pre-switch-capture
```

Expected: local and remote hashes match. Do not create a `v1.22.02` release tag.

- [ ] **Step 5: Create the implementation branch and add the approved documents**

```powershell
git switch -c codex/account-switch-foreground-bitblt
git add -- docs/superpowers/specs/2026-09-01-account-switch-foreground-bitblt-design.md docs/superpowers/plans/2026-09-01-account-switch-foreground-bitblt.md
git commit -m "docs: plan foreground account switch capture"
```

Expected: implementation branch starts from the backed-up candidate commit; Android paths remain unstaged.

---

### Task 2: Expand the task-scoped capture session to the full account transition

**Files:**
- Modify: `src/logout_capture.py`
- Modify: `src/runtime/login_flow_service.py`
- Modify: `src/task/MultiAccountDailyTask.py`
- Modify: `tests/TestLogoutCapture.py`
- Modify: `tests/TestRuntimeServices.py`
- Modify: `tests/TestMultiAccountDailyTask.py`

**Interfaces:**
- Preserve `CaptureSample(frame, origin, hwnd, source, captured_at)` and `ObservedBox(box, sample)`.
- Produce `AccountSwitchCaptureSession.capture_main() -> CaptureSample | None`.
- Preserve `LogoutCaptureSession` as a temporary alias to avoid breaking focused tests during migration.
- Produce `MultiAccountDailyTask._create_account_switch_capture_session() -> context manager`.
- `LoginFlowService.switch_to_account()` owns the session and stores it only in `task._active_account_switch_capture` inside a `try/finally` boundary.

- [ ] **Step 1: Write failing lifecycle tests**

Add tests that use a fake context manager and assert:

```python
def test_login_flow_owns_one_capture_session_for_the_whole_switch():
    assert events == [
        "capture_enter", "wait_login", "select", "login", "ensure_main", "capture_exit"
    ]


def test_login_flow_clears_capture_reference_after_failure():
    with self.assertRaises(RuntimeError):
        LoginFlowService(task).switch_to_account("A3")
    self.assertIsNone(task._active_account_switch_capture)
    self.assertEqual(events[-1], "capture_exit")
```

Also cover `TaskDisabledException` and a capture constructor failure that yields `nullcontext(None)` without changing the task result.

- [ ] **Step 2: Run the lifecycle tests and verify failure**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestLogoutCapture.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestRuntimeServices.py
```

Expected: new tests fail because the service does not yet own a full-switch session.

- [ ] **Step 3: Generalize the existing session without adding a second capture backend**

Implement the naming transition in `src/logout_capture.py`:

```python
class AccountSwitchCaptureSession:
    def __init__(self, hwnd_window, exit_event, capture_factory=ForegroundBitBltCaptureMethod):
        ...

    def capture_main(self):
        # Keep existing foreground-before, frame validation,
        # foreground-after and origin checks unchanged.
        ...


LogoutCaptureSession = AccountSwitchCaptureSession
```

Do not add dependencies, global capture mutation, background threads or caching of OCR boxes.

- [ ] **Step 4: Make LoginFlowService own and clean up the session**

Wrap the existing production sequence with:

```python
factory = getattr(task, "_create_account_switch_capture_session", None)
context = factory() if callable(factory) else nullcontext(None)
with context as capture_session:
    task._active_account_switch_capture = capture_session
    try:
        # Existing logout, wait, select, login and ensure_main calls remain here.
        ...
    finally:
        task._active_account_switch_capture = None
```

The outer service evidence and `MouseResetTask` cleanup remain in their existing `finally` blocks.

- [ ] **Step 5: Run lifecycle tests and commit**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestLogoutCapture.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestRuntimeServices.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestMultiAccountDailyTask.py
git add -- src/logout_capture.py src/runtime/login_flow_service.py src/task/MultiAccountDailyTask.py tests/TestLogoutCapture.py tests/TestRuntimeServices.py tests/TestMultiAccountDailyTask.py
git diff --cached --name-only
git commit -m "refactor: scope capture to account transitions"
```

Expected: tests pass and no Android path is staged.

---

### Task 3: Route every main-window account-switch observation through foreground BitBlt first

**Files:**
- Modify: `src/task/MultiAccountDailyTask.py`
- Modify: `tests/TestMultiAccountDailyTask.py`

**Interfaces:**
- Produce `_capture_account_switch_main_sample() -> CaptureSample | None`.
- Preserve `_capture_logout_main_sample(session)` as a delegating compatibility wrapper.
- Produce `_ocr_account_switch_main() -> tuple[list, CaptureSample] | tuple[None, None]`.
- Main-window helpers consume the active sample origin instead of calling implicit WGC coordinate conversion.
- Dialog and Combo controls continue to use `_capture_hwnd_client(hwnd)` unchanged.

- [ ] **Step 1: Add failing capture-source and coordinate-provenance tests**

Add focused tests asserting:

```python
def test_main_login_observation_prefers_active_foreground_capture():
    texts, sample = task._ocr_account_switch_main()
    self.assertEqual(sample.source, "foreground_bitblt")
    self.assertEqual(task.wgc_calls, 0)


def test_invalid_foreground_frame_falls_back_to_one_fresh_wgc_frame():
    texts, sample = task._ocr_account_switch_main()
    self.assertEqual(sample.source, "wgc")
    self.assertEqual(task.wgc_calls, 1)


def test_bitblt_ocr_box_uses_the_same_sample_origin_for_sendinput():
    self.assertEqual(clicked_point, (sample.origin[0] + 125, sample.origin[1] + 240))
```

Cover empty, pure-color, invalid-size and foreground-changed failure reasons, and assert that no failure causes input in an unknown state.

- [ ] **Step 2: Run the focused tests and verify failure**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestMultiAccountDailyTask.py
```

Expected: new tests fail because main login observations still call implicit WGC OCR.

- [ ] **Step 3: Implement a single foreground-first main sample helper**

Use the active session when present and preserve the existing safe WGC fallback:

```python
def _capture_account_switch_main_sample(self):
    main_hwnd, _pid = self._main_window_identity()
    if not main_hwnd:
        return None
    session = getattr(self, "_active_account_switch_capture", None)
    if session is not None and self._bring_account_window_to_front(main_hwnd):
        self.sleep(0.2)
        sample = session.capture_main()
        if sample is not None:
            return sample
        self.log_warning(
            f"账号切换前台截图不可用（{session.last_reason}），本轮回退 WGC"
        )
    frame = self.next_frame()
    origin = self.hwnd.get_capture_origin() if frame is not None else None
    if frame is None or not origin:
        return None
    return CaptureSample(
        frame=frame,
        origin=(int(origin[0]), int(origin[1])),
        hwnd=int(main_hwnd),
        source="wgc",
        captured_at=time.monotonic(),
    )
```

- [ ] **Step 4: Route main-window login helpers through one sample per decision**

Update these paths to use `_ocr_account_switch_main()` or an explicitly passed `CaptureSample`:

- `_wait_login_screen_stable()` main-window branch;
- `do_find_account_drop_down()` main-window branch;
- `_main_login_screen_click()`;
- `_account_list_expanded()` when no `ComboLBox`/dialog is active;
- `_detect_current_account_from_login()` main-window branch;
- `_click_account_in_list()` main-window branch;
- `_visible_login_profiles()` main-window branch;
- logout `_logout_state()` and `_find_logout_button_target()` through the compatibility wrapper.

Each action must use `ObservedBox(box, sample)` or `sample.origin`; no action may call `_main_box_center_screen()` for a box created from foreground BitBlt.

- [ ] **Step 5: Preserve independent-window capture priority**

Keep the selection order:

```python
if visible_same_pid_dialog:
    capture_and_ocr_that_hwnd()
elif visible_same_pid_combo_lbox:
    capture_and_ocr_that_hwnd()
else:
    capture_account_switch_main_sample()
```

Do not attempt to composite `#32770` or `ComboLBox` into the main BitBlt frame.

- [ ] **Step 6: Run capture routing tests and commit**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestMultiAccountDailyTask.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestLogoutCapture.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestWin32LoginInput.py
rg -n "set_capture|DeviceManager\.set_capture" src/logout_capture.py src/task/MultiAccountDailyTask.py src/runtime/login_flow_service.py
git add -- src/task/MultiAccountDailyTask.py tests/TestMultiAccountDailyTask.py
git commit -m "feat: prefer foreground capture while switching accounts"
```

Expected: tests pass; the search finds no global capture mutation.

---

### Task 4: Fix the pending “点击连接” entry and exact login-button matching

**Files:**
- Modify: `src/task/BaseWWTask.py`
- Modify: `src/task/MultiAccountDailyTask.py`
- Modify: `tests/TestWaitLogin.py`
- Modify: `tests/TestMultiAccountDailyTask.py`

**Interfaces:**
- Produce `CONNECT_TEXTS` for exact “点击连接”/supported locale entry labels.
- Produce `_exact_login_button_boxes(texts, boundary=None)` that rejects status text.
- Produce `_find_connect_target(sample, texts) -> ObservedBox | None`.
- `_wait_login_screen_stable()` owns a maximum of three connect-entry attempts and only advances on observed state change.

- [ ] **Step 1: Add failing semantic-safety tests**

Add tests covering:

```python
def test_login_status_text_is_never_treated_as_login_button():
    texts = [TextBox("登录状态：0")]
    self.assertEqual(task._exact_login_button_boxes(texts), [])


def test_click_connect_is_matched_only_in_bottom_center_boundary():
    target = task._find_connect_target(sample, [TextBox("点击连接", x=1100, y=1300)])
    self.assertEqual(target.sample, sample)


def test_connect_click_retries_with_fresh_samples_until_dialog_appears():
    task._wait_login_screen_stable(time_out=10)
    self.assertEqual(task.capture_count, 3)
    self.assertEqual(task.click_count, 2)
    self.assertTrue(task._login_in_dialog)
```

Also assert: a connect target outside the permitted bottom-center region is ignored; three delivered-but-unconfirmed clicks raise the existing login-screen timeout; `TaskDisabledException` stops immediately without another capture or click.

- [ ] **Step 2: Run the new tests and verify failure**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestWaitLogin.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestMultiAccountDailyTask.py
```

Expected: new tests fail under broad `LOGIN_TEXTS` matching and passive stable waiting.

- [ ] **Step 3: Add exact button semantics**

Filter OCR candidates with full-button matches:

```python
LOGIN_BUTTON_RE = re.compile(r"^(?:登录|登入|登錄|Log\s*In)$", re.IGNORECASE)
CONNECT_BUTTON_RE = re.compile(
    r"^(?:点击连接|點擊連接|Click\s+(?:to\s+)?(?:Connect|Start))$",
    re.IGNORECASE,
)
```

`_exact_login_button_boxes()` may use existing `find_boxes()` for boundary filtering, but must apply `fullmatch()` to each returned OCR name before any coordinate is accepted.

- [ ] **Step 4: Make BaseWWTask distinguish connect entry from account login**

In `wait_login()`:

1. inspect the bottom-center region for `CONNECT_BUTTON_RE`;
2. click only that exact target through existing `_click_login_box()`;
3. log “点击连接入口” rather than “点击登录按钮”;
4. only when no connect entry exists, search for exact login buttons;
5. preserve the existing `+86` guard and transient auto-login settle behavior.

This prevents “登录状态：0” from producing a false delivered login click before `LoginFlowService` starts.

- [ ] **Step 5: Add bounded connect-entry retries to the production switch waiter**

Inside `_wait_login_screen_stable()`:

```python
connect_attempts = 0
...
target = self._find_connect_target(sample, texts)
if target is not None and connect_attempts < 3:
    connect_attempts += 1
    delivered = self._click_main_login_box(
        target.box,
        stage="connect_entry",
        after_sleep=1,
        origin=target.sample.origin,
    )
    self._evidence_stage(
        "connect_entry_result",
        attempt=connect_attempts,
        detail=f"delivered={bool(delivered)},confirmed=False",
    )
    self.sleep(1)
    continue
```

Confirmation occurs only when a later fresh observation finds the account dropdown or same-PID independent login dialog. The waiter must never call generic `wait_login()` because that could submit the currently displayed account before target selection.

- [ ] **Step 6: Run login tests and commit**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestWaitLogin.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestMultiAccountDailyTask.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestRuntimeServices.py
git add -- src/task/BaseWWTask.py src/task/MultiAccountDailyTask.py tests/TestWaitLogin.py tests/TestMultiAccountDailyTask.py
git commit -m "fix: enter the account login screen reliably"
```

Expected: exact-entry, retry, cancellation and existing account-login tests pass.

---

### Task 5: Lock independent-window foreground and SendInput behavior

**Files:**
- Modify: `src/win32_login_input.py` only if a new failing test exposes a missing invariant.
- Modify: `tests/TestWin32LoginInput.py`
- Modify: `tests/TestMultiAccountDailyTask.py`
- Modify: `tests/TestAccountSwitch.py`

**Interfaces:**
- Preserve `force_foreground(target_hwnd, expected_pid) -> ForegroundResult`.
- Preserve `send_input_click(target_hwnd, expected_pid, point) -> LoginClickDelivery`.
- `ComboLBox` allowance remains limited to same PID, valid point, valid target rect and verified foreground.
- No new click backend is introduced.

- [ ] **Step 1: Add regression tests for changing foreground targets**

Cover this exact sequence with fake HWNDs:

```python
main_hwnd -> dialog_hwnd -> combo_box_hwnd -> combo_lbox_hwnd -> dialog_hwnd -> main_hwnd
```

For each action assert that `force_foreground()` is called for the fresh target, `WindowFromPoint` belongs to the game PID, and stale prior HWND coordinates are not reused.

- [ ] **Step 2: Add explicit refusal tests**

Assert rejection for:

- same-process but unrelated non-allowlisted top-level windows;
- ComboLBox point outside its real rectangle;
- target hidden/disabled/destroyed after capture;
- foreground changed after capture;
- partial SendInput delivery;
- any attempt to call PostMessage from account selection.

- [ ] **Step 3: Run tests before changing the input boundary**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestWin32LoginInput.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestMultiAccountDailyTask.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestAccountSwitch.py
```

Expected: most tests pass with the existing SendInput boundary. Change `src/win32_login_input.py` only for a reproducible failing invariant, not for speculative refactoring.

- [ ] **Step 4: Apply the smallest boundary fix if required and commit tests**

```powershell
git add -- tests/TestWin32LoginInput.py tests/TestMultiAccountDailyTask.py tests/TestAccountSwitch.py
if (git diff --quiet -- src/win32_login_input.py) { } else { git add -- src/win32_login_input.py }
git diff --cached --name-only
git commit -m "test: lock account switch window targeting"
```

Expected: no PostMessage production path and no unrelated Win32 refactor.

---

### Task 6: Synchronize version 1.22.03 and rebuild the update package

**Files:**
- Modify: `config.py`
- Modify: `custom_ok/ok/gui/about/AboutTab.py`
- Modify: `更新日志.md`
- Modify: `tests/TestReleaseReadiness.py`
- Verify: `打包更新.py`
- Generate but do not stage: `okww_更新包_20260901.zip`

**Interfaces:**
- Product version is exactly `1.22.03`.
- Release notes mention task-scoped foreground BitBlt, WGC fallback, exact connect-entry handling, per-HWND dialog capture and verified SendInput.

- [ ] **Step 1: Add the failing release-readiness expectation**

Update the version assertion to require:

```python
self.assertEqual(version, "1.22.03")
```

and assert that About and the changelog contain `1.22.03` plus the four release themes.

- [ ] **Step 2: Run the release test and verify failure**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestReleaseReadiness.py
```

Expected: failure because product metadata still reports `1.22.02`.

- [ ] **Step 3: Synchronize product metadata**

Set `config.py` to `1.22.03`; add matching top entries to About and `更新日志.md`. Do not alter account configuration or Android metadata.

- [ ] **Step 4: Verify and rebuild**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestReleaseReadiness.py
.\.venv\Scripts\python.exe .\scripts\validate_release.py --tag v1.22.03
.\.venv\Scripts\python.exe .\打包更新.py
```

Expected: validator prints `1.22.03`; the ZIP includes changed source, COCO data, power icon, About and changelog, while excluding logs, screenshots, account configs and Android user data.

- [ ] **Step 5: Inspect ZIP contents without extracting over the workspace**

```powershell
.\.venv\Scripts\python.exe -c "import zipfile; p='okww_更新包_20260901.zip'; z=zipfile.ZipFile(p); n=set(z.namelist()); required={'src/task/BaseWWTask.py','src/task/MultiAccountDailyTask.py','src/runtime/login_flow_service.py','src/logout_capture.py','src/win32_login_input.py','config.py','custom_ok/ok/gui/about/AboutTab.py','更新日志.md'}; assert required <= n; assert not any(x.startswith(('logs/','screenshots/','android/agent-app/')) for x in n); print(len(n))"
```

Expected: assertion succeeds and prints the packaged file count.

- [ ] **Step 6: Commit release metadata but not the ZIP**

```powershell
git add -- config.py custom_ok/ok/gui/about/AboutTab.py 更新日志.md tests/TestReleaseReadiness.py 打包更新.py
git diff --cached --name-only
git commit -m "chore: prepare 1.22.03"
```

Expected: generated ZIP and Android paths remain unstaged.

---

### Task 7: Run automated regression and controlled A3/A4 real-world verification

**Files:**
- No planned source files; failures return to the owning task above with a new failing test first.
- Runtime logs/screenshots/evidence remain untracked and must not be committed.

**Interfaces:**
- Produces automated test evidence and one complete A3/A4 runtime result.
- The real test starts through OKWW; no manual game click may substitute for program behavior.

- [ ] **Step 1: Run all focused tests in isolated processes**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestLogoutCapture.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestWaitLogin.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestWin32LoginInput.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestRuntimeServices.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestAccountSwitch.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestAccountSwitchEvidence.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestMultiAccountDailyTask.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestDailyTaskStatus.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestFeatureSet.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestReleaseReadiness.py
```

Expected: all pass; no test calls real SendInput.

- [ ] **Step 2: Compile and inspect the complete diff**

```powershell
.\.venv\Scripts\python.exe -m compileall -q src custom_ok tests
git diff --check
git status --short
git diff --stat codex/backup-v1.22.02-pre-switch-capture..HEAD
```

Expected: compile and whitespace checks pass; diff contains only this plan’s files; Android dirt remains separate.

- [ ] **Step 3: Restart the packaged/latest 1.22.03 application without interacting with the game manually**

Use Computer Use only to observe a fresh OKWW window, select the task page and start “多账号每日任务”. Before every UI input, obtain a fresh window state. Do not click inside the game to help the automation pass.

Expected starting state: the game may still be on “点击连接”; OKWW must handle it itself.

- [ ] **Step 4: Verify the pending connect-entry fix**

Confirm sanitized logs show:

- one task-scoped capture session entered;
- foreground BitBlt used or an explicit WGC fallback reason recorded;
- exact “点击连接” target used, never “登录状态”；
- `delivered` and `confirmed` recorded separately;
- account login window becomes observable within the configured timeout.

- [ ] **Step 5: Verify the complete A3/A4 flow**

Confirm:

- the persisted completed account is skipped by short name;
- the remaining account is selected through the actual `ComboLBox`/dialog or main embedded path;
- the status window continues to display only A3/A4 short names;
- target account is verified before login;
- the remaining account’s complete daily task finishes;
- final return to the starting account succeeds when configured;
- task ends normally without an unhandled warning/error.

- [ ] **Step 6: Handle any runtime failure through TDD**

For each failure:

1. stop the current OKWW task;
2. sanitize and inspect logs/evidence;
3. identify the producing method and add one failing fake-based regression test;
4. make the smallest correction in that method;
5. rerun Tasks 6 and 7 from the affected test onward;
6. rebuild the update ZIP and restart the latest application;
7. resume A3/A4 testing without manually advancing the game.

Do not broaden window-class allowlists or relax account verification to make a test pass.

---

### Task 8: Publish only the verified 1.22.03 release

**Files:**
- No new source changes.
- Verify all implementation and release commits on `codex/account-switch-foreground-bitblt`.

**Interfaces:**
- Produces `origin/master` and annotated tag `v1.22.03` pointing to the same verified commit.
- Preserves the separate `1.22.02` backup branch.

- [ ] **Step 1: Read and follow the repository deploy skill**

Read `E:\AI work\better wuwa\.agents\skills\deploy\SKILL.md` completely before any tag or push, then apply it subject to this plan’s explicit Android exclusions.

- [ ] **Step 2: Verify branch contents and clean staging area**

```powershell
git status --short
git diff --cached --name-only
git log --oneline --decorate codex/backup-v1.22.02-pre-switch-capture..HEAD
```

Expected: staging is empty; only known Android work and generated ZIP remain uncommitted; implementation commits are present.

- [ ] **Step 3: Fast-forward master to the verified implementation branch**

```powershell
git switch master
git merge --ff-only codex/account-switch-foreground-bitblt
```

Expected: fast-forward succeeds without touching Android working-tree files.

- [ ] **Step 4: Re-run final release gates on master**

```powershell
.\.venv\Scripts\python.exe .\scripts\validate_release.py --tag v1.22.03
.\.venv\Scripts\python.exe -m compileall -q src custom_ok tests
git diff --check
```

Expected: version `1.22.03`, compile success and no whitespace errors.

- [ ] **Step 5: Create and push the annotated release**

```powershell
git tag -a v1.22.03 -m "v1.22.03"
git push origin master
git push origin v1.22.03
```

Expected: both pushes target the correct OKWW GitHub repository.

- [ ] **Step 6: Verify remote hashes**

```powershell
git fetch origin --tags
git rev-parse HEAD
git rev-parse origin/master
git rev-parse "v1.22.03^{}"
git ls-remote origin refs/heads/codex/backup-v1.22.02-pre-switch-capture
```

Expected: HEAD, `origin/master` and dereferenced tag hashes are identical; the backup branch still exists.

---

## Plan Self-Review

- [x] Full-switch capture lifecycle, cleanup and WGC fallback are covered by Tasks 2-3.
- [x] The previously unimplemented “点击连接” design and false “登录状态” match are covered by Task 4.
- [x] Independent `#32770`/ComboBox/ComboLBox BitBlt and fresh foreground targeting are covered by Tasks 3 and 5.
- [x] No task introduces global capture switching, PostMessage login fallback, fixed coordinates, UIA selection or direct ComboBox selection messages.
- [x] Existing production/test service reuse is preserved.
- [x] Current candidate backup precedes business-code edits.
- [x] Version, package, controlled runtime test, tag, push and remote verification are explicit.
- [x] Every Python command uses the repository-local virtual environment.
- [x] Android paths, runtime evidence, secrets and generated ZIP files are excluded from commits.
