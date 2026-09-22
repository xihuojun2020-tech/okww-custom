# Account Reminders and Echo Targets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify account reminders, add notes, expose four optional nightmare-settlement targets, and compact the account configuration layout.

**Architecture:** Keep reminders in account extensions and fully detach them from completion evidence. Preserve the existing residual-settlement field, add a separate optional nightmare-settlement field, and let the farming task filter the two game pages independently. Reuse the existing account editor and task snapshot path so identity and sequence protections remain intact.

**Tech Stack:** Python, PySide6, ok-script task configuration, unittest.

**Spec:** User-approved requirements in the 2026-09-22 Codex thread.

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

- [ ] Replace project-derived reminders with six stable display-only values.
- [ ] Add a bounded multiline per-account note and preserve unrelated extensions.
- [ ] Remove reminder summaries and reminder filtering from Completion Check.
- [ ] Run focused reminder and completion-check tests.

### Task 2: Optional nightmare settlements

**Files:** `src/nightmare_nests.py`, `src/task/NightmareNestTask.py`, `src/task/DailyTask.py`, `src/config_integrity.py`, `src/account_field_metadata.py`, account template and task tests.

**Interfaces:** Add `NIGHTMARE_NAMES` and `FARM_NIGHTMARE_SETTLEMENTS`; missing/new values resolve to `[]` while residual targets retain their existing values.

- [ ] Add the four ordered in-game names with an empty default.
- [ ] Filter residual and nightmare pages against their own selected lists.
- [ ] Pass the new selection through daily, capture, recovery, and checkpoint signatures.
- [ ] Preserve legacy fields for import compatibility while hiding the obsolete type selector.
- [ ] Run focused task, integrity, and migration tests.

### Task 3: Account layout

**Files:** `src/gui/AccountConfigTab.py`, UI tests.

**Interfaces:** Produce one target-selection control for residual and nightmare settlements and one compact weekly-status widget.

- [ ] Place sequence membership inside “账号识别信息”.
- [ ] Merge stamina fields into “日常与声骸”.
- [ ] Merge weekly boss fields into “周常安排”.
- [ ] Replace three weekly status setting rows with a compact grid.
- [ ] Verify wide and narrow layouts with focused UI tests.

### Task 4: Release validation

**Files:** `config.py`, `更新日志.md`, relevant reference documentation.

**Interfaces:** Release version `1.84.00` and matching annotated tag `v1.84.00`.

- [ ] Update version and user-facing documentation.
- [ ] Run focused tests, then the repository test command.
- [ ] Commit the verified change and create the annotated tag.
- [ ] Push the branch and tag to GitHub and publish the update to the approved NAS path.
