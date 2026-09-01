# PC-only Android Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the abandoned Android/MuMu experiment from the active okww product without changing PC capture, input, account switching, or daily-task behavior.

**Architecture:** Preserve the complete current Android worktree state in a repository-external ZIP before deletion. Remove only Android-specific source, assets, scripts, tests, and design documents; remove the disabled Android configuration and update-package references, while retaining the three harmless `_android_boundary` compatibility guards for this release.

**Tech Stack:** Python 3, PowerShell, Git, unittest, ZIP archive

**Spec:** User-approved in-thread PC-only isolation design, 2026-09-01

## Global Constraints

- Do not start or control Wuthering Waves during verification.
- Preserve all uncommitted Android work in `E:\AI work\废弃代码` before deleting it.
- Do not change WGC, Foreground BitBlt, SendInput, account switching, or daily-task behavior.
- Use `\.venv\Scripts\python.exe` for all Python commands.
- Use fixed-width version `1.23.00` because this is a medium-sized product-scope removal.
- Commit only this removal, create annotated tag `v1.23.00`, and push the branch and tag to `origin`.

---

### Task 1: Archive the abandoned Android experiment

**Files:**
- Archive: `src/android/`, `android/`, `assets/android/`, Android-specific scripts, tests, custom Nemu capture shim, and Android/MuMu plans/specs
- Create: `E:\AI work\废弃代码\okww-android-experiment-20260901.zip`

- [ ] **Step 1:** Copy the explicit Android file set into a temporary staging directory while preserving repository-relative paths.
- [ ] **Step 2:** Add an archive manifest containing the source repository, branch, HEAD, dirty status, and archived path list.
- [ ] **Step 3:** Compress the staging directory and verify the ZIP can be listed and contains modified and untracked Android files.

### Task 2: Remove Android-only product files

**Files:**
- Delete: `src/android/`, `android/`, `assets/android/`, `custom_ok/ok/device/capture_methods/nemu_ipc.py`
- Delete: `probe_mumu.py`, `scripts/preflight_mumu.py`
- Delete: `tests/TestAndroidPreflight.py`, `tests/TestMuMuDiscovery.py`
- Delete: Android/MuMu-specific plans and specs

- [ ] **Step 1:** Delete the archived explicit file set; do not use broad globs outside those directories.
- [ ] **Step 2:** Search the active tree for production imports or packaging references to removed modules.

### Task 3: Clean product configuration and packaging

**Files:**
- Modify: `config.py`
- Modify: `打包更新.py`
- Modify: `tests/TestReleaseReadiness.py`
- Modify: `custom_ok/ok/gui/about/AboutTab.py`
- Modify: `更新日志.md`

- [ ] **Step 1:** Add a release-readiness assertion that the product config and update package no longer expose Android/MuMu artifacts.
- [ ] **Step 2:** Run the focused assertion and confirm it fails before implementation.
- [ ] **Step 3:** Remove `android_config`, the top-level `android` entry, and `probe_mumu.py` from the update package list.
- [ ] **Step 4:** Set all product-facing version text to `1.23.00` and document the archive location and retained compatibility guards.
- [ ] **Step 5:** Run the focused test and confirm it passes.

### Task 4: Verify PC-only behavior and packaging

**Files:**
- Test: existing release, unit, integration, fault-injection, UI, and image groups

- [ ] **Step 1:** Run syntax compilation and release validation for `v1.23.00`.
- [ ] **Step 2:** Run focused PC account-switch and task-status tests without starting the game.
- [ ] **Step 3:** Run all documented test groups.
- [ ] **Step 4:** Generate an update ZIP and verify it contains no `src/android`, Android Agent, Nemu shim, Android JAR, or MuMu probe.

### Task 5: Publish the isolated PC release

**Files:**
- Commit only the planned removal and release files.

- [ ] **Step 1:** Review staged paths and confirm the archive itself remains outside the repository.
- [ ] **Step 2:** Commit using the repository's current commit-message language.
- [ ] **Step 3:** Create annotated tag `v1.23.00` and push `HEAD` plus the tag to `origin`.
- [ ] **Step 4:** Verify the remote branch and peeled tag target the published commit.
