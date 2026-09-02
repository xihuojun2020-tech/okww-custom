# Multi-Account Daily Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Execute this plan task-by-task with tests before implementation. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent stale account settings, recover from transient Nightmare Nest UI failures, bound Aemeath's heavy-action loop, and avoid premature combat exits without changing the game-driving test policy.

**Architecture:** Keep the existing task and character classes. Make the selected verified profile authoritative for the duration of a daily run, recover Nightmare Nest navigation at its existing boundaries, and add small bounded state guards to character/combat polling. Reuse existing task waits, status reporting, and test fakes; add no dependencies.

**Tech Stack:** Python, ok-script task helpers, unittest/pytest, Git.

**Spec:** Approved in-chat diagnosis for `多账号每日任务错误汇总_20260902.zip`.

## Global Constraints

- Do not start or control Wuthering Waves during verification.
- Use `\.venv\Scripts\python.exe` for Python commands.
- Keep changes compatible with production `DailyTask`, `MultiAccountDailyTask`, and `TestAccountSwitchTask` paths.
- Update the fixed-width release version to `1.25.00` and synchronize release metadata.
- Commit, create annotated tag `v1.25.00`, and push the branch and tag after offline verification.

---

### Task 1: Preserve the verified daily profile

**Files:**
- Modify: `src/task/MultiAccountDailyTask.py`
- Modify: `src/task/DailyTask.py`
- Test: `tests/TestConfigIntegrity.py`

**Interfaces:**
- Consumes: `DailyTask.bind_verified_profile(profile_name, expected_profile_id=None)`.
- Produces: a run-scoped verified profile binding that `ensure_daily_profiles()` cannot replace with a stale UI selector.

- [ ] Add a regression test where the target profile differs from `DailyTask.config['Daily Profile']`.
- [ ] Verify the test fails because `ensure_daily_profiles()` rebinds the stale selector.
- [ ] Synchronize the runtime selector and verified ID at the multi-account execution boundary, then validate the bound ID before reading profile fields.
- [ ] Log the bound profile ID and the effective Nightmare/farming settings.
- [ ] Run the focused account/config tests.

### Task 2: Recover Nightmare Nest navigation

**Files:**
- Modify: `src/task/NightmareNestTask.py`
- Modify: `src/task/DailyTask.py`
- Test: `tests/TestNightmareNestTask.py`

**Interfaces:**
- Consumes: `openF2Book`, `wait_in_team_and_world`, `ensure_main`, and existing travel feature helpers.
- Produces: bounded book-opening retries and a stable travel transition check without replacing `ensure_main` on the task instance.

- [ ] Add tests for a slow travel-button disappearance, retryable book-open failure, and exhaustion of bounded retries.
- [ ] Verify the new tests fail against the one-second/unbounded-recovery behavior.
- [ ] Wait for either a world transition or stable failure before marking a nest unreachable.
- [ ] Retry reopening the book after restoring a known world state.
- [ ] Replace the `ensure_main` monkey patch with an explicit run option controlling only final cleanup.
- [ ] Run Nightmare Nest and DailyTask tests.

### Task 3: Bound Aemeath's heavy-action loop

**Files:**
- Modify: `src/char/Aemeath.py`
- Test: `tests/TestChar.py`

**Interfaces:**
- Consumes: `has_long_action`, `handle_heavy`, `time_elapsed_accounting_for_freeze`, and `switch_next_char`.
- Produces: an 8-second bounded pre-rotation loop that always releases control back to team rotation.

- [ ] Add a regression test with `has_long_action()` permanently true.
- [ ] Verify the test detects the unbounded behavior using a controlled fake clock.
- [ ] Add the minimum deadline guard and warning log while preserving the existing successful-heavy behavior.
- [ ] Run Aemeath/character tests.

### Task 4: Confirm combat exit across an observation window

**Files:**
- Modify: `src/combat/CombatCheck.py`
- Test: `tests/TestCombatCheck.py`

**Interfaces:**
- Consumes: `has_target`, `target_enemy`, `combat_end_condition`, monthly-card handling, and scene combat state.
- Produces: consecutive target-loss confirmation with reset on positive target evidence.

- [ ] Add tests for one transient failed retarget, recovery during the observation window, and confirmed repeated misses.
- [ ] Verify a single failed retarget currently resets combat.
- [ ] Track the first unresolved target-loss time and require a bounded grace period before reset.
- [ ] Preserve explicit combat-end conditions as immediate exits.
- [ ] Run CombatCheck and combat-character tests.

### Task 5: Keep stamina accounting non-negative

**Files:**
- Modify: `src/task/BaseWWTask.py`
- Test: `tests/TestBaseWWTask.py` or the closest existing stamina test module.

**Interfaces:**
- Consumes: the OCR-derived current/backup/total stamina tuple.
- Produces: non-negative projected current and total values after a claim, with truthful remaining-total logging.

- [ ] Add a test for `current=0`, `backup=106`, and a 60-cost claim.
- [ ] Verify current code projects `current=-60`.
- [ ] Clamp projected pools while preserving the correct `total < once` stop decision.
- [ ] Run the focused stamina/domain tests.

### Task 6: Release verification and publishing

**Files:**
- Modify: `config.py`
- Modify: `tests/TestReleaseReadiness.py`
- Modify: `custom_ok/ok/gui/about/AboutTab.py`
- Modify: `更新日志.md`

**Interfaces:**
- Produces: synchronized release `1.25.00` / `v1.25.00`.

- [ ] Run focused regression tests for all changed modules.
- [ ] Run the repository's full offline test suite.
- [ ] Update version and product-facing release notes to `1.25.00`.
- [ ] Run release-readiness validation and inspect the final diff.
- [ ] Stage only intended files and commit in the repository's existing English subject style.
- [ ] Create annotated tag `v1.25.00` and push the branch and tag to `origin`.
