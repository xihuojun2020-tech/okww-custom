# Daily outcome repair implementation plan

**Goal:** Repair the September 15 failures, including lost tab input, invalid resource OCR, false echo checkpoints, missed chests, and missing recovery transitions.

**Architecture:** Keep the existing task hierarchy and bounded navigation adapter. Share pure daily-page/resource observations, verify outcomes before checkpoints, and retain account-bound consumption guards.

**Tech Stack:** Python, ok-script, OpenCV, unittest and recorded screenshots.

**Spec:** docs/reviews/2026-09-16-multiaccount-sept15-followup.md (approved by user).

Execution is already authorized; execute inline. Preserve unrelated working-tree changes. Product version is 1.78.00 because this changes several cooperating task behaviors. Do not claim device acceptance from offline tests.

- [x] Add `src/task/daily_observation.py`: unambiguous spatial resource parsing and scaled reward-marker observations. Verify 80/240 + 159, unknown/ambiguous numbers, and recorded 90-point chests.
- [x] In BaseWWTask verify requested guide content after a tab click, with bounded navigation and one reopen; apply new-frame retry to invalid claim readings.
- [x] In DailyTask share daily-page navigation across execution/recording; distinguish unknown spent stamina from zero; read echo task state across bounded scrolls and verify before writing/skipping capture checkpoints.
- [x] Replace fixed reward fallback with tier-specific red-marker detection, bounded clicks, modal handling, and post-claim checks. Test lost click and unchanged markers.
- [ ] Add bounded activity completion based on actual missing objectives; retain full/unknown reserve revocation and exact conversion checks. Resume only after an observed recovery and positive progress, never multiply account retry count.
- [x] Handle exact weekly story-travel modal once, verify original boss after confirming, preserve pending weekly outcome through repeated calls. Keep login/switch implementation shared with TestAccountSwitchTask.
- [x] Replay NAS frames through production OCR and detection, run focused logic/navigation/account-switch tests, register new test files in the repository manifest, run wider required verification.
- [x] Synchronize config.py and changelog; commit only owned files, annotated v1.78.00, push branch/tag, build/publish matching NAS update with the existing release script; document offline/real-device verification boundary.

Commands use `.venv/Scripts/python.exe scripts/run_test_file.py tests/<file>.py`; image tests derive sanitized fixtures from `test_out/nas_0915_audit/frames`. Confirm each meaningful behavior with assertions (wrong content must not reach resource reading; echo 0/1 must defeat old checkpoint; red markers remaining must defeat claim success).

Recovery code and remaining-progress budgets are implemented, including material-planner routing and progress-bounded continuation. Reserve preconversion accepts only an explicit exact shortfall with verified balances; automatic adjustment of an unknown/default-bulk modal remains unimplemented because no actual modal sample is available. That item is deliberately not checked off. See `docs/reviews/2026-09-16-daily-outcome-implementation.md` for verification limits and device acceptance steps.
