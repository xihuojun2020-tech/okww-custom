# Feature Navigation Implementation Plan

> **For agentic workers:** Execute task-by-task inline in this approved task. The suggested executing-plans/subagent-driven-development skills are not available in this session; use the existing tools with verification checkpoints.

**Goal:** Give every existing feature one predictable home in five pages.

**Architecture:** Keep native Qt headers and single-scroll page containers. Centralize pure navigation/category mappings, move existing widgets to their new owners, preserve controllers and compatibility routes.

**Tech Stack:** Python, PySide6, existing QFluentWidgets, repository-local .venv.

**Spec:** `docs/superpowers/specs/2026-09-09-feature-navigation-design.md`

## Global Constraints

- No task registration, visibility, account transaction, weekly scheduling or safety-confirmation changes.
- Exactly five project pages; tools/settings use bottom navigation. No About page.
- No added dependencies, nested page scrolls or nested collapsible category containers.
- One StartTab/hotkey handler, one account plan editor, one backup-directory control.
- Version 1.47.00; preserve pre-existing docs/reviews deletions outside the release commit.

## Task 1: Navigation and task grouping

Files: `src/gui/navigation_sections.py`, `custom_ok/ok/gui/tasks/TaskTab.py`, `OneTimeTaskTab.py`, `TriggerTaskTab.py`, `src/gui/TaskHubTab.py`, `tests/TestNavigationSections.py`.

- [x] Assert manifest titles equal `['任务', '账号', '自动辅助', '工具', '设置']`, with first three `position='scroll'`, last two `position='bottom'`.
- [x] Implement `canonical_section(section)`, `task_category(task)`, `helper_category(task)` as pure functions. Legacy activities map to tasks; legacy tests map to tools.
- [x] Rebuild non-collapsible group labels when task lists refresh; preserve task-card expansion via existing cache. Sort categories before constructing cards; never show empty group labels.
- [x] Run `.\.venv\Scripts\python.exe -m unittest tests.TestNavigationSections tests.TestTaskNavigationClassification`.

## Task 2: Move existing controls into five page owners

Files: `src/gui/GeneralSettingsTab.py`, new `AssistantHubTab.py`, new `ToolsHubTab.py`, `AccountSettingsTab.py`, `custom_ok/ok/gui/start/StartTab.py`, `custom_ok/ok/gui/settings/SettingTab.py`, `custom_ok/ok/gui/MainWindow.py`.

- [x] Settings constructs the single StartTab; AssistantHubTab receives `start_panel` and reparents its StartCard, retaining callbacks. ToolsHubTab receives `start_panel` and reparents diagnostic/overlay controls.
- [x] Move maintenance SettingTab out of AccountSettingsTab. Split maintenance groups by backup, restore and integrity; retain the same signals and BackgroundOperation controls.
- [x] Embed the preferences SettingTab into settings; skip duplicate backup controls and duplicate Start/Stop field. Move diagnostics to tools and updates stay in settings.
- [x] Map old start/general routes to settings, trigger to assistant, activities to tasks, tests to tools. Route backup config lookup to tools and other config lookup to settings.
- [x] Update `TestFiveSectionMainWindow` and run isolated UI tests.

## Task 3: Account field categories and unique edit entry

Files: `src/gui/AccountConfigTab.py`, `custom_ok/ok/gui/tasks/TaskCard.py`, `tests/TestFlatUI.py`.

- [x] Keep weekly boss group separate. Move garden/weekly merge to weekly arrangements and logout to finish behavior; do not change stored keys or values.
- [x] Keep account-scoped task fields read-only on the task page. Override only GUI management buttons to navigate to account/sequence editor, preserving existing task methods for non-GUI use.
- [x] Test distinct groups, collapsed defaults, draft preservation and management navigation without invoking legacy dialogs.

## Task 4: Verification and publishing

- [x] Update renderer to construct the same five page owners as MainWindow and include all visible registered task metadata with inert devices.
- [x] Run UI and full isolated suites; render at 760/1100 widths, closed/expanded, 100/125/150/200% scale. Inspect actual images and verify no lost/duplicated task or maintenance entries.
- [x] Update README, changelog, architecture, handoff and UI reference/verification documents and screenshots.
- [ ] Validate via `.\.venv\Scripts\python.exe scripts/validate_release.py --tag v1.47.00`; stage only scoped changes, commit, annotate tag and push branch/tag after confirming tag availability.

Release checkpoint: validation passed for 1.47.00; remote tag is vacant. Commit/tag/push are the final actions after this document is staged; their confirmed result belongs to the task's final response. Verification evidence: `docs/references/ui-disclosure-verification.md`.
