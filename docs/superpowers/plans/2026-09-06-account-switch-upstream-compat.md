# Upstream-Compatible Account Switch Optimization Implementation Plan

**Goal:** Reduce account-switch instability by adopting the original okww's low-state switching flow while retaining profile mapping, independent-window handling, verification, sequence progress, and return-to-start-account behavior.

**Architecture:** Keep `MultiAccountDailyTask` as the orchestration point. During one account transition, reuse one capture session and only refresh the HWND snapshot after a no-frame/handle-change signal. Use PostMessage for main-window controls and SendInput for controls belonging to an independent login window. Confirm dropdown expansion by a visible account-count transition, then require consecutive identity matches before login.

**Tech Stack:** Python 3, ok-script task helpers, existing BitBlt/WGC capture services, existing account identity and window-input helpers, unittest.

**Spec:** The user-approved upstream-compatible account-switch optimization described in chat on 2026-09-06.

## Global Constraints

- Do not operate the game during development or testing.
- Preserve configured sequence order, aliases, masked-phone matching, progress persistence, failure reporting, and final return to the initial account.
- Keep the account-switch test entry point synchronized with production methods.
- Any code release increments `config.py` using fixed-width `X.YY.ZZ`, updates release notes, creates an annotated tag, and pushes branch and tag.

### Task 1: Capture-session stability

**Files:**
- Modify: `src/task/MultiAccountDailyTask.py` transition capture helpers and account-switch orchestration.
- Test: `tests/TestAccountSwitchEvidence.py` and `tests/TestAccountSwitch.py`.

- [ ] Reuse the existing account-switch capture session for the complete logout/list-selection/login transition.
- [ ] Remove per-OCR/per-retry capture backend changes; refresh the HWND snapshot only after no-frame or handle replacement.
- [ ] Add offline tests asserting capture mode remains stable across retries and refresh is bounded to failure signals.

### Task 2: Original-compatible dropdown and identity flow

**Files:**
- Modify: `src/task/MultiAccountDailyTask.py` account-list open, expansion, OCR, and selection verification methods.
- Test: `tests/TestMultiAccountDailyTask.py`, `tests/TestAccountSwitch.py`.

- [ ] Detect collapsed state with one mapped account entry and expanded state with at least two entries or a recognized list region.
- [ ] OCR the current transition frame for the full visible list and select the first uncompleted configured profile in display order.
- [ ] Keep normalization and aliases, require two consecutive displayed-account matches, and retry up to five times.
- [ ] Keep login-button OCR first and fixed-coordinate fallback second, with a bounded state-change confirmation.

### Task 3: Window-aware click routing

**Files:**
- Modify: `src/task/MultiAccountDailyTask.py` and existing `src/win32_login_input.py` integration points.
- Test: `tests/TestWin32LoginInput.py`, `tests/TestAccountSwitch.py`.

- [ ] Route main-window controls through PostMessage.
- [ ] Route controls whose HWND/PID belongs to the independent login window through SendInput screen coordinates.
- [ ] Record the selected click mode in evidence/logs without exposing account secrets.

### Task 4: Release verification

**Files:**
- Modify: `config.py`, `更新日志.md`, `custom_ok/ok/gui/about/AboutTab.py`, `tests/TestReleaseReadiness.py`.

- [ ] Run focused offline account-switch, runtime-service, logout-capture, and release-readiness tests with the repository `.venv` interpreter.
- [ ] Run `git diff --check` and stage only intended files.
- [ ] Increment the patch version, commit the change, create the matching annotated tag, and push branch plus tag to `origin`.
- [ ] Confirm the remote tag and clean worktree; do not launch or control the game.
