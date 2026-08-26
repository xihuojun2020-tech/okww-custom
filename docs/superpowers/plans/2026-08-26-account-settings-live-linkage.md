# Account Settings Live Linkage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make account, sequence, daily-task, multi-account, and account-switch-test UI consumers refresh immediately after an account/sequence publication without changing an already-running immutable task snapshot.

**Architecture:** The account-settings hub owns a small Qt signal carrying the published change kind, affected profile/sequence IDs, and revision. Account and sequence editors emit it only after successful repository publication; the hub refreshes its sibling panels and forwards the event to the main window, which refreshes task-card options in place. Runtime tasks continue to freeze a `SequenceRunSnapshot` at start.

**Tech Stack:** Python 3, PySide6 `Signal`, existing `AccountRepository` CAS publication, ok-script task cards, unittest.

**Spec:** `docs/superpowers/specs/2026-08-26-account-profile-security-and-identity-design.md`

## Global Constraints

- Keep per-account UUID isolation and active snapshot publication intact.
- `masked_phone` remains the primary account-switch identity; `alternate_login_name` is fallback; `game_feature_code` remains display-only.
- Do not mutate a running task's frozen `SequenceRunSnapshot`; changes apply to the next run.
- Preserve unrelated user-owned working-tree changes.
- Keep product version text synchronized with the current repository release (`1.18.00`).

---

### Task 1: Define the account-change event contract

**Files:**
- Modify: `src/gui/AccountConfigTab.py`
- Modify: `src/gui/SequenceManagementTab.py`
- Modify: `src/gui/AccountSettingsTab.py`
- Test: `tests/TestAccountManagementTabs.py`

**Interfaces:**
- Produces `AccountChangeEvent(kind: str, revision: str, profile_ids: tuple[str, ...], sequence_ids: tuple[str, ...])` and `AccountSettingsTab.account_changed`.
- `AccountConfigTab.changed` and `SequenceManagementTab.changed` emit the event after a successful save/delete/publication.

- [x] Add a small immutable event dataclass and `Signal(object)` declarations in the three Qt widgets; use kinds `profile_saved`, `profile_deleted`, `sequence_changed`.
- [x] Emit `profile_saved` with the edited UUID and all affected sequence IDs after `save_draft` succeeds; emit `profile_deleted` after cascade deletion.
- [x] Emit `sequence_changed` after create/copy/rename/toggle/delete/reorder succeeds, preserving the selected sequence ID where possible.
- [x] Connect both child signals in `AccountSettingsTab`; refresh the sibling account/sequence panel and re-emit one hub-level signal.
- [x] Add source-level tests asserting the signal contract and that each successful operation routes through the hub callback.

### Task 2: Refresh the account-settings sibling panels

**Files:**
- Modify: `src/gui/AccountConfigTab.py`
- Modify: `src/gui/SequenceManagementTab.py`
- Test: `tests/TestAccountManagementTabs.py`

**Interfaces:**
- `AccountConfigTab.refresh(profile_id: str | None = None)` preserves the selected UUID when still present.
- `SequenceManagementTab.refresh(sequence_id: str | None = None)` preserves the selected sequence and re-renders its members.

- [x] Make `AccountConfigTab.refresh` accept an optional profile ID, repopulate profiles, then select that UUID before rendering sequence checkboxes.
- [x] Make `SequenceManagementTab.refresh` accept an optional sequence ID and call `_show_members()` after restoring the row.
- [x] In `AccountSettingsTab`, on `profile_saved` refresh both panels; on `profile_deleted` refresh both and fall back to the first valid account/sequence; on `sequence_changed` refresh both while preserving the selected IDs.
- [x] Add tests for A1 moving from sequence1 to sequence2 and for deleting a profile referenced by a sequence.

### Task 3: Refresh DailyTask and MultiAccountDailyTask controls

**Files:**
- Modify: `src/task/DailyTask.py`
- Modify: `src/task/MultiAccountDailyTask.py`
- Modify: `custom_ok/ok/gui/tasks/TaskCard.py` only if an in-place card refresh hook is required
- Test: `tests/TestAccountRuntimeIntegration.py`

**Interfaces:**
- `DailyTask.refresh_account_options()` synchronizes sequence/profile options and updates the existing card widgets without rebuilding the task tab.
- `MultiAccountDailyTask.refresh_account_options()` synchronizes sequence names, visible account labels, and current-selection fallbacks without touching `_active_run_snapshot`.

- [x] Extend DailyTask's existing `_sync_sequence_options` path to update both `方案序列` and `Daily Profile` combos, selecting a valid fallback when the old value disappeared.
- [x] Add a MultiAccountDailyTask refresh method that rereads the repository projection, updates `config_type`, and updates the existing card's combo/label widgets in place.
- [x] Ensure a refresh skips mutation when the task is running and instead records a pending refresh for the next run; never change `create_run_snapshot` output after start.
- [x] Add tests that publish a new sequence/profile and assert the task methods expose it immediately, plus a running-snapshot immutability test.

### Task 4: Refresh the account-switch test entry point

**Files:**
- Modify: `src/task/TestAccountSwitchTask.py`
- Test: `tests/TestAccountRuntimeIntegration.py`

**Interfaces:**
- `TestAccountSwitchTask.refresh_profile_options()` rereads the account repository projection and updates the target-account options in its existing card.

- [x] Replace the startup-only integrity projection fallback with the same active-snapshot repository loader used by MultiAccountDailyTask.
- [x] Add the refresh method and preserve `（自动识别）` plus the current target when still valid.
- [x] Route the account-settings hub event through MainWindow to this method.

### Task 5: Wire MainWindow and maintenance actions

**Files:**
- Modify: `custom_ok/ok/gui/MainWindow.py`
- Modify: `custom_ok/ok/gui/settings/SettingTab.py`
- Modify: `src/task/DailyTask.py`
- Test: `tests/TestFiveSectionMainWindow.py`

**Interfaces:**
- `MainWindow.refresh_account_consumers(event)` calls the three task refresh methods and never rebuilds the five top-level pages.

- [x] Connect `AccountSettingsTab.account_changed` after all five hub/task tabs are constructed.
- [x] Refresh DailyTask, MultiAccountDailyTask, and TestAccountSwitchTask cards in place; report a safe status if a task is absent.
- [x] After import, restore, or legacy-sequence repair, emit the same event or call the hub refresh so settings and task pages converge.
- [x] Add a main-window wiring test that uses fake task consumers and verifies all three are called once per event.

### Task 6: Documentation and regression verification

**Files:**
- Modify: `更新日志.md`
- Modify: `custom_ok/ok/gui/about/AboutTab.py`
- Modify: `docs/handover/2026-08-26-account-profile-security-handover.md`

- [x] Document immediate account/sequence/task linkage and the running-snapshot boundary.
- [x] Run focused account/UI/runtime unittest groups and `compileall` with the repository `.venv` interpreter.
- [x] Run the full unittest suite; record only the known image-task `FinishedException` failures if unchanged.
- [x] Preserve all unrelated uncommitted files and report the final commit/tag state separately.
