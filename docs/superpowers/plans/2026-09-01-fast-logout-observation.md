# Fast Logout Observation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the PC logout portion of account switching use cheap visual checks first and OCR only the return-to-login button region.

**Architecture:** Keep the existing `MultiAccountDailyTask` state machine and BitBlt capture session. Reorder one-frame observation so the return-login ROI and existing templates decide `confirm`, `setting`, and `main`; run the expensive full-screen login OCR only after those states fail, while preserving dropped-click recovery.

**Tech Stack:** Python 3.12, ok-script task helpers, OpenCV template matching, ONNXPaddleOCR, `unittest`.

**Spec:** User-approved in-thread design from 2026-09-01.

## Global Constraints

- Do not start, click, or otherwise operate Wuthering Waves during verification.
- Continue capturing the complete foreground monitor through task-scoped BitBlt.
- Match `RETURN_LOGIN_TEXTS` only inside the right-center confirmation-button ROI.
- Keep account selection and composite login-window recognition on full-monitor OCR.
- Preserve unrelated Android worktree changes.
- Release the verified small fix as `1.22.05` with synchronized product version and release notes.

---

### Task 1: Lock the optimized observation order with tests

**Files:**
- Modify: `tests/TestMultiAccountDailyTask.py`

**Interfaces:**
- Consumes: `MultiAccountDailyTask._logout_state(capture_session=None) -> str`
- Produces: regression coverage for template-first observation, ROI OCR, and delayed login OCR

- [ ] **Step 1: Add a test that setting detection does not call full-screen login OCR**

```python
def test_logout_state_checks_setting_before_login_fullscreen_ocr(self):
    # A captured setting frame returns ``setting`` through esc_setting.
    # Any call to do_find_account_drop_down must fail the test.
```

- [ ] **Step 2: Add a test that return-login OCR receives the bounded ROI**

```python
def test_logout_state_uses_return_login_roi(self):
    # Record ocr(x, y, to_x, to_y, frame=...) and assert
    # (0.50, 0.52, 0.80, 0.72) plus RETURN_LOGIN_TEXTS.
```

- [ ] **Step 3: Add a test that full-screen login OCR remains the final fallback**

```python
def test_logout_state_checks_login_after_local_visual_states_miss(self):
    # With no confirm/setting/main match, return login when the existing
    # do_find_account_drop_down helper reports a login identity.
```

- [ ] **Step 4: Run the focused tests and verify they fail for the intended ordering/ROI reasons**

Run: `.\.venv\Scripts\python.exe -m unittest tests.TestMultiAccountDailyTask`

Expected: the new tests fail because `_logout_state` currently performs login OCR first and calls `ocr(frame=...)` on the complete frame.

### Task 2: Implement the minimum state-machine change

**Files:**
- Modify: `src/task/MultiAccountDailyTask.py`
- Test: `tests/TestMultiAccountDailyTask.py`

**Interfaces:**
- Consumes: existing `CaptureSample`, `find_one`, `ocr`, `find_boxes`, `in_team_and_world`, and `do_find_account_drop_down`
- Produces: `_logout_state(capture_session=None) -> str` with cheap local states before the full-screen login fallback

- [ ] **Step 1: Perform return-login OCR on the actual right-center crop**

```python
return_login = self.ocr(
    0.50, 0.52, 0.80, 0.72,
    frame=sample.frame,
    match=RETURN_LOGIN_TEXTS,
)
```

- [ ] **Step 2: Keep confirm templates, `esc_setting`, and world detection on the same captured frame**

Do not introduce a new capture, cache, helper class, dependency, or template.

- [ ] **Step 3: Move `do_find_account_drop_down(prefer_dialog=True)` to the final fallback**

Only use full-screen login OCR after return-login, confirm, setting, and world checks miss.

- [ ] **Step 4: Avoid full-screen OCR in the power-button fallback**

After `logout_power_icon` misses, verify `esc_setting` on the same frame and use the established `LOGOUT_POWER_POSITION`. Do not scan the full frame for `LOGOUT_TEXTS`.

- [ ] **Step 5: Run focused task tests**

Run: `.\.venv\Scripts\python.exe -m unittest tests.TestMultiAccountDailyTask tests.TestLogoutCapture tests.TestFeatureSet`

Expected: PASS.

### Task 3: Release and publish version 1.22.05

**Files:**
- Modify: `config.py`
- Modify: `custom_ok/ok/gui/about/AboutTab.py`
- Modify: `更新日志.md`
- Modify: release-readiness expectations when required by the existing tests

**Interfaces:**
- Consumes: repository versioning and release-readiness conventions
- Produces: synchronized product-facing `1.22.05` metadata and annotated `v1.22.05` tag

- [ ] **Step 1: Update all product-facing version and release-note entries to `1.22.05`**

- [ ] **Step 2: Run the complete standard-library test suite**

Run: `.\.venv\Scripts\python.exe -m unittest discover -s tests`

Expected: PASS without launching or operating the game.

- [ ] **Step 3: Inspect only intended changes**

Run: `git diff --check` and `git diff -- <intended files>`.

- [ ] **Step 4: Commit the release**

```powershell
git add -- config.py custom_ok/ok/gui/about/AboutTab.py src/task/MultiAccountDailyTask.py tests/TestMultiAccountDailyTask.py tests/TestReleaseReadiness.py 更新日志.md docs/superpowers/plans/2026-09-01-fast-logout-observation.md
git commit -m "fix: speed up account logout observation"
```

- [ ] **Step 5: Tag and push**

```powershell
git tag -a v1.22.05 -m v1.22.05
git push origin HEAD v1.22.05
```
