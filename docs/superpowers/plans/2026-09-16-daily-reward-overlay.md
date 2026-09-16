# Daily Reward Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Fix the approved A3 reward-overlay interruption without bypassing completion checks.

**Architecture:** Reuse DailyTask's shared claim-page restoration for objective and chest rewards. Detect overlays before background anchors, wait for stable daily frames, then continue the existing mail/battle-pass/weekly/recording chain.

**Tech Stack:** Python, ok-script, unittest, production OCR screenshot replay.

**Spec:** NAS diagnosis `2026-09-16-a3-reward-overlay-interruption.md` in the original workspace; user approved on 2026-09-16.

## Global Constraints

- Preserve released 1.79.01 features and unrelated workspace edits.
- Only NAS `\\192.168.3.173\羲火君 共享给我\AI诊断`; no live account operation.
- Use local `.venv/Scripts/python.exe`; patch version 1.79.02, annotated tag and GitHub/NAS publication after verification.
- Superpowers execution subskills are not available in this session. Execute inline using the approved design; no delegation.

### Task 1: Reward restoration and failure summary

Files: `src/task/DailyTask.py`, `src/task/MultiAccountDailyTask.py`; tests in existing `TestDailyActivityFlow.py`, `TestDailyRegressionFlow.py`, `TestDailyOutcomeRecovery.py`, `TestDailyRegressionImages.py`, `TestMultiAccountDailyTask.py`.

- [x] Add failing overlay tests, including animation, background anchors, stuck overlay, delayed appearance, and all tiers awarded together. Restore helper returns a verified daily frame; no F2 reopening during overlay.
- [x] Run `.venv/Scripts/python.exe scripts/run_test_file.py tests/TestDailyActivityFlow.py` and confirm the regression fails.
- [x] Implement `_daily_reward_overlay(frame)` with title and bottom continue-prompt OCR; `_restore_daily_claim_page()` with at most 16 samples and 3 blank clicks, requiring consecutive normal frames.
- [x] Route chest clicks and final verification through the shared helper; validate red dots only on the returned daily frame.
- [x] Test real `claim_daily` inside `_run_daily_inner`: mail, battle pass, weekly tasks and recording precede completion; stuck overlay prevents all later steps and completion.
- [x] Make `_finish_sequence` say `本轮结束，仍有账号未完成` when unresolved failures exist, retaining stored stage/reason. No login changes.
- [x] Replay masked incident frames using production OCR and run affected test files, then `./run_tests.ps1 -Group all`.

### Task 2: Version and publication

- [x] Set `config.py` to `1.79.02`, prepend matching `更新日志.md` entry, and save substantive implementation/verification report.
- [x] Inspect targeted diff, commit only intended files, create annotated `v1.79.02`, push branch and tag.
- [x] Run `.venv/Scripts/python.exe 打包更新.py dist`; verify package with `scripts/verify_update_package.py --previous-ref v1.79.01`.
- [x] Check NAS stable latest has not advanced; publish using `scripts/publish_lan_update.py` to `OKWW-Updates`, verify receipt and hash. Record that offline checks are not live-device acceptance.
