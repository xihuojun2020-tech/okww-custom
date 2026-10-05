# Domain Combat Recovery Implementation Plan

**Goal:** Repair full-bar stamina reading, revive cooldown switching, domain combat continuation, and result-page handoff while preserving verified reward accounting and persistent auto combat.

**Architecture:** Extend the existing shared observation and combat helpers; route domain, Tacet, and multi-account recovery through explicit scene evidence. Keep combat ownership and verified resource accounting in their existing code paths.

**Tech Stack:** Python, ok-script task classes, OpenCV OCR, unittest, repository-local virtual environment.

**Spec:** `docs/reviews/2026-10-05-extended-nas-investigation.md` and the user-approved four-part solution in this conversation.

## Constraints

- Start from the latest released tag, currently `v1.97.08`; preserve its target names and account configurations.
- Only a user toggle may disable persistent auto combat. Never send simultaneous foreground and background combat input.
- Do not count a reward, spend stamina twice, or start another challenge without verified claim evidence.
- Publish the next patch version once all four fixes pass; reserve `2.00.00`.
- Keep diagnostic reports and evidence within the designated NAS share and okww监控室.

## Tasks

### 1. Establish baseline and fixture tests

**Files:** `tests/TestStaminaAccounting.py`, `tests/TestTrioCombatRecovery.py`, `tests/TestDomainRecoveryLoop.py`, `tests/TestTacetRewardRecovery.py`, `tests/TestDailyFailureRecovery.py`.

- [x] Merge `v1.97.08` into the existing clean worktree and confirm the version is `1.97.08`.
- [x] Add a regression using the reviewed full-240 resource image; assert `(240, 480, 720)` and reject 240 in unrelated dialog regions.
- [x] Add cooldown switch tests using the reviewed banner image and synthetic refreshed frames; verify temporary exclusion, later eligibility, and no hard disable.
- [x] Add domain tests where `combat` persists past two recovery checks and victory animation precedes reward entry.
- [x] Add Tacet and account-recovery tests for victory, failure, loading, pending claim, and confirmed settlement.

### 2. Fix full-bar stamina observation

**Files:** `src/task/BaseWWTask.py`, `src/task/daily_observation.py`.

- [x] Extend only anchored top-bar reading to accept exact bare `240` after fresh, consistent observations; preserve the strict fraction path and independent reserve reading.
- [x] Keep unknown as `(-1, -1, -1)` when anchors are absent or values conflict.
- [x] Run `TestStaminaAccounting` and image tests.

### 3. Fix revival cooldown rotation

**Files:** `src/task/BaseCombatTask.py`, `tests/TestTrioCombatRecovery.py`, `tests/TestAutoCombatRecovery.py`.

- [x] Distinguish a failed switch with explicit cooldown banner from no-item rejection and ordinary input failure.
- [x] Exclude the rejected target only until its cooldown expires or a verified revival clears it; keep surviving-character skills and liberation available.
- [x] Test three-person and sole-survivor rotation, expired cooldown, and manual disable.

### 4. Continue live domain combat and classify result states

**Files:** `src/task/DomainTask.py`, `src/task/BaseWWTask.py`, `tests/TestDomainRecoveryLoop.py`.

- [x] Treat confirmed `combat` as the same challenge, without a two-attempt terminal error; use a bounded no-progress diagnostic independent from auto-combat enablement.
- [x] Recognize success animation as a transition, never reward proof; wait for a fresh claim/treasure frame.
- [x] Keep explicit challenge failure recovery and verified `use_stamina` accounting.

### 5. Correct Tacet and account recovery handoff

**Files:** `src/task/TacetTask.py`, `src/task/MultiAccountDailyTask.py`, `tests/TestTacetRewardRecovery.py`, `tests/TestDailyFailureRecovery.py`.

- [x] Inspect current scene before `wait_in_team_and_world`; handle success transition, failure, loading, claim prompt, and settlement explicitly.
- [x] After uncertain claim, preserve pending status and evidence, and forbid another claim/restart until balance or result is verified.
- [x] Account recovery must not blindly escape a pending reward page.

### 6. Verify and publish

**Files:** `config.py`, `README.md`, `更新日志.md`, release verification document.

- [x] Run focused regression suites and the full repository test gate through the local `.venv`.
- [x] Simulate upgrading existing account settings and inspect screenshots/evidence paths.
- [x] Increment the patch version once, synchronize product text, commit, tag, push branch and tag to GitHub.
- [x] Publish the tested package to NAS, download and verify its SHA256; report real-game verification limits.
