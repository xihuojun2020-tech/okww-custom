# Account Reminders and Echo Targets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify account reminders, add notes, expose four optional nightmare-settlement targets, and compact the account configuration layout.

**Architecture:** Keep reminders in account extensions and fully detach them from completion evidence. Preserve the existing residual-settlement field, add a separate optional nightmare-settlement field, and let the farming task filter the two game pages independently. Reuse the existing account editor and task snapshot path so identity and sequence protections remain intact.

**Tech Stack:** Python, PySide6, ok-script task configuration, unittest.

**Spec:** User-approved requirements in the 2026-09-22 Codex thread.

**Implementation result:** Completed and released as `1.84.00`, commit `b87b4ee0`, annotated tag `v1.84.00`. The branch and tag were published to GitHub and the update package was published to the approved NAS path. 152 focused tests passed. The repository runner initially stopped on the isolated worktree's shared `.venv` path-ownership check; after removing that junction, the check passed independently. No game session was started, so live first-page/scrolled nightmare-settlement clicking remains user acceptance work.

## Global Constraints

- New nightmare settlements default to an empty selection.
- Use the four in-game names and the term “梦魇聚落”.
- Reminders and notes are display-only and have no completion-evidence behavior.
- Move sequence membership into account identity information.
- Merge stamina into “日常与声骸” and weekly boss into “周常安排”.
- Update fixed-width version, release notes, tests, commit, annotated tag, GitHub and NAS.

---

### Task 1: Reminder model and editor

**Files:** `src/account_reminders.py`, `src/gui/AccountReminderPanel.py`, `src/gui/CompletionCheckTab.py`, reminder tests.

**Interfaces:** Produce `get_reminders`, `set_reminders`, `get_reminder_note`, and `set_reminder_note`; completion evidence consumes none of them.

- [x] Replace project-derived reminders with six stable display-only values.
- [x] Add a bounded multiline per-account note and preserve unrelated extensions.
- [x] Remove reminder summaries and reminder filtering from Completion Check.
- [x] Run focused reminder and completion-check tests.

### Task 2: Optional nightmare settlements

**Files:** `src/nightmare_nests.py`, `src/task/NightmareNestTask.py`, `src/task/DailyTask.py`, `src/config_integrity.py`, `src/account_field_metadata.py`, account template and task tests.

**Interfaces:** Add `NIGHTMARE_NAMES` and `FARM_NIGHTMARE_SETTLEMENTS`; missing/new values resolve to `[]` while residual targets retain their existing values.

- [x] Add the four ordered in-game names with an empty default.
- [x] Filter residual and nightmare pages against their own selected lists.
- [x] Pass the new selection through daily, capture, recovery, and checkpoint signatures.
- [x] Preserve legacy fields for import compatibility while hiding the obsolete type selector.
- [x] Run focused task, integrity, and migration tests.

### Task 3: Account layout

**Files:** `src/gui/AccountConfigTab.py`, UI tests.

**Interfaces:** Produce one target-selection control for residual and nightmare settlements and one compact weekly-status widget.

- [x] Place sequence membership inside “账号识别信息”.
- [x] Merge stamina fields into “日常与声骸”.
- [x] Merge weekly boss fields into “周常安排”.
- [x] Replace three weekly status setting rows with a compact grid.
- [x] Verify wide and narrow layouts with focused UI tests.

### Task 4: Release validation

**Files:** `config.py`, `更新日志.md`, relevant reference documentation.

**Interfaces:** Release version `1.84.00` and matching annotated tag `v1.84.00`.

- [x] Update version and user-facing documentation.
- [x] Run focused tests and the repository test command, recording the isolated-worktree path limitation described above.
- [x] Commit the verified change and create the annotated tag.
- [x] Push the branch and tag to GitHub and publish the update to the approved NAS path.
