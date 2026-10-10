# GameFrame remaining graphical surfaces implementation plan

> **For agentic workers:** Implement task by task using executing-plans; delegation requires explicit authorization. Parent owns release integration.

**Goal:** Replace remaining legacy graphical controls with controls backed by the actual native device, session, configuration and storage owners.

**Architecture:** Keep GameFrame launcher options responsible for device selection and the management configuration owner responsible for persistent package settings. Route live operations through the existing session owner; never open a second capture/input device from management UI. Reuse verified storage migration primitives while keeping output storage distinct from the native package data root.

**Audit scope:** Static reads only on 2026-10-11. No Windows enumeration, emulator/ADB/SDK execution, game input, NAS operations or account operations were performed. Character editing and script bundles are outside this audit. This document is a plan, not evidence of live device compatibility.

## Existing surfaces and actual gaps

| Legacy surface | Native status / remaining work |
| --- | --- |
| `GeneralSettingsTab` / `StartTab` device picker | `gameframe/gui.py` still edits device JSON. Add graphical selection bound to `gameframe/worker.py:create_device`. |
| Start/Stop hotkey and game-key conflict display | Native game-key configuration exists. Application hotkey routing and its persisted preference need a native control and session/controller integration. |
| Notification preferences | Native task logs carry `notify`; host emits `combat-notification`. These events need an explicit launcher notification route and graphical preferences. Legacy transport settings alone do not establish native delivery. |
| Tools capture/OCR/directories/log export | Evidence, diagnostics and maintenance already have native surfaces. Add only absent manual capture/OCR and path actions after checking existing tabs. |
| Assistant services and foreground tasks | Native session/service controls already exist. Preserve these controls and saved enabled intent; do not transplant the legacy task manager. |
| Account backup/import/integrity/recovery | Native maintenance already owns these operations. No parallel implementation. |
| Storage location | Existing bootstrap migrates named output kinds. Launcher `data_dir / manifest.id` also owns configs, scripts and runtime data; this is a separate root and cannot be moved by pretending output migration covers it. |

## Task 1 — graphical device selection (highest priority)

**Files:** `gameframe/gui.py`, `gameframe/devices/windows.py` only for a narrowly scoped read-only discovery API if needed, and existing `tests/TestGameFrameDevices.py` plus a Qt launcher fixture test.

- [ ] Replace the primary JSON-only interaction with backend choice and backend-specific fields; retain advanced JSON only if useful for existing launch options. Round-trip through existing `load_options` / option saving, not a second settings file.
- [ ] Windows: select an HWND from a refreshable list showing title and process identity; alternatively configure the existing absolute `launch_command` and `target_executable`. `WindowsDevice` currently supports WGC and SendInput. Show those concrete methods; do not expose legacy BitBlt/PostMessage choices without implementing and verifying them separately.
- [ ] Use a backend-injected enumeration seam for tests. Do not enumerate on module import or start a device during a configuration-owner request. Revalidate the selected window when the worker opens it; existing PID/create-time binding protects window replacement during execution.
- [ ] MuMu: expose `install_dir`, `instance_index`, optional `dll_path`, `package_name`, `app_index`; explain the external SDK requirement using the actual constructor contract. LeiDian: offer the existing ADB backend with serial and `adb_path`; no dedicated LeiDian SDK exists in this tree.
- [ ] Render capability compatibility against the selected task before start. Windows supplies keyboard/mouse; MuMu supplies frames/multitouch; ADB supplies frames/tap/swipe/keyevent. Current WW tasks requiring frames/keyboard/mouse cannot be advertised as MuMu/ADB compatible. Preserve the runtime capability rejection as the authoritative boundary.
- [ ] Freeze selection while a worker owns the device, as the current launcher already freezes device JSON. Switching device means a stopped session followed by a new worker.
- [ ] Verify option round-trip, exact constructor payloads, incompatible-task rejection and busy UI using fixtures/Replay. No actual emulator/game testing is required for this implementation test cycle.

**Acceptance:** A Windows user can select an existing game window without writing JSON. Emulator choices honestly display supported tasks; selecting them does not manufacture keyboard/mouse support.

## Task 2 — application hotkey and notifications

**Files:** `gameframe/gui.py`, existing launcher/controller event handling, native global configuration schema and `src/runtime/native_combat_host.py` only where the live owner must handle a command. Locate the current controller module before editing; do not build a second controller.

- [ ] Add the existing None/F9/F10/F11/F12 preference and conflict indication against configured game keys. Define its action as the same session pause/resume operation used by the GUI. Explicit service disabling remains a separate action; hotkey pause must not persist auto-combat disabled.
- [ ] Ensure pause can be resumed: polling only inside a paused combat loop is insufficient. Put the application hotkey in the controller/event-loop boundary, or a session control loop that remains alive while paused. Debounce by key transition, with an injected key-state fixture.
- [ ] Consume `combat-notification` and notified `task-log` events once in the launcher; show title/message/failure using existing Qt facilities and a Windows tray notification preference. Include task completion/failure events only where the current event contract provides them.
- [ ] Audit actual legacy transport implementations before migrating remote notification settings. Expose a provider only when its native delivery implementation exists and can report failure. Do not promise QQ/WeChat desktop automation or copy credential values into logs/exported launcher JSON.
- [ ] Migrate only corresponding existing preferences, preserving explicit disabled values. Do not copy Basic Options wholesale: DirectML, resize, mute, exit-on-game-exit and launcher-kill switches need actual native behavior before being displayed.
- [ ] Verify hotkey press/release, paused resume, game-key conflict, one notification per event and preserved service intent with injected Qt/session fixtures.

**Acceptance:** GUI and hotkey invoke the same pause semantics, and notification UI corresponds to observable delivery behavior.

## Task 3 — owner-bound manual tools

**Files:** Existing native management/evidence tabs, `src/runtime/native_combat_host.py`, session request dispatch, and `src/runtime/native_task.py` capture/OCR helpers as needed. Keep the legacy `ToolsHubTab` and `StartTab` out of the native import path.

- [ ] Inventory existing native buttons first; reuse diagnostic exports, evidence browsing and maintenance rather than duplicating them.
- [ ] Add screenshot and OCR requests processed by the current live device owner at a safe task boundary. Use existing capture/OCR behavior and native evidence paths; never start another capture thread from the management process. A stopped session should clearly require starting a session rather than silently opening hardware.
- [ ] Return saved path and OCR result/errors via the existing request/reply protocol. Legacy `StartTab.ocr_log_bg` uses the first legacy task and swallows errors into a log; do not reproduce that ownership or failure behavior.
- [ ] Add open-data/log/screenshot-directory actions using resolved current paths. Overlay debug controls are optional only if a native overlay renderer actually exists; the legacy widget is not proof of one.
- [ ] Verify owner ordering, unavailable-session response and screenshot/OCR artifacts using Replay and an OCR fixture. No key input or second device owner should be created by these requests.

**Acceptance:** Manual inspection yields an artifact/result through the current owner without concurrent input or hidden hardware initialization.

## Task 4 — storage location visibility and output migration

**Files:** Existing native management tab, `src/runtime/storage_bootstrap.py`, `storage_startup_ui.py`, `storage_handoff.py`, `diagnostic_storage.py`, `src/storage.py`, `src/native_maintenance.py`; edit migration internals only for a demonstrated native integration gap.

- [ ] First display both native package data root and resolved output paths, with open-folder actions. `prepare_native_data` manages backup/recovery under the explicit package root; it does not call the legacy storage bootstrap.
- [ ] Offer output relocation only through `storage_bootstrap.migrate` after all relevant owners have stopped/closed. Existing policy requires a local destination on the installation drive outside the update directory; keep this policy unless the user explicitly changes it.
- [ ] Reuse source inventory, SQLite/WAL snapshot, SHA verification, journal and final config commit. Keep originals. Use `storage_handoff.quiesce_uploaders` for this installation's scheduled uploader ownership where that integration applies; never run an unowned global stop command.
- [ ] Verify the selected `repo` is the actual configuration authority read by native `storage_path(..., repo=data_dir)`. A migration written only to installation `configs/runtime_storage.json` does not prove a native package root will read it. Resolve this binding before enabling the action.
- [ ] Reopen configuration/session owners against the committed paths. Distinguish copy/verification failure from a committed switch whose owner restart fails, following existing maintenance committed-failure behavior.
- [ ] Test same-drive/path policy, source preservation, active data-lease refusal and changed output resolution with temporary directories and mocked handoff. Existing `tests/TestStorageBootstrap.py` covers core copy behavior; extend only for the native binding gap.

**Separate decision:** Full launcher data-root relocation is not implemented by output-kind migration. If required, stop all package/config/overview owners, obtain exclusive data leases, inventory the whole root including configs/user_tasks/launcher state/databases, copy and verify, then atomically switch the launcher root and reopen owners. Do not ship a partial move labeled as full migration. This needs its own concrete root-selection contract before coding; displaying the existing root is immediately implementable.

**Retired features:** KRLauncher SequenceBackups may remain a historical migration source. Do not restore KR multi-instance management. Windows user switching stays manual.

## Verification and release boundary

- [ ] Execute only the focused fixture/Replay/Qt/temp-directory tests relevant to each completed task, using the repository `.venv` interpreter. These checks establish protocol/UI/storage correctness, not real hardware success.
- [ ] Inspect added protection branches against observed failures and constructor/owner contracts; delete unsupported fallback/retry behavior.
- [ ] Parent integrates version/release notes and ordinary verified commit/tag/push for code changes. This audit document alone has no version change or release action. Wait for the parent’s v71 release before implementing further surfaces.
