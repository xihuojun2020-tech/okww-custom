# ok-ww 易用性与数据安全综合优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留现有 PC 识别、登录和战斗行为的前提下，完成身份保护、可恢复配置发布、任务解耦、UI 易用性和分层测试改造。

**Architecture:** 以 `active bundle` 作为运行时唯一真源，账号/序列仓库负责 CAS 校验、事务发布和只读投影。账号选择、序列快照、登录流程、任务协调和 UI 状态逐步拆成边界清晰的服务；运行任务始终消费不可变快照。

**Tech Stack:** Python 3.12、PySide6/qfluentwidgets、现有 `AccountRepository`/`AccountPublishService`、Windows DPAPI、JSON、unittest/pytest、项目本地 `.venv`。

**Spec:** `docs/superpowers/specs/2026-08-26-comprehensive-hardening-design.md`

## Global Constraints

- PC 端是本计划的主运行路径；Android/MuMu 保持独立、显式启用的实验链路。
- `profile_id`、`phone`、`masked_phone`、`nickname`、`alternate_login_name`、`game_feature_code`、`account_aliases` 在普通账号编辑流程中不可修改。
- `masked_phone` 是切换首要识别依据，`alternate_login_name` 是备用识别名，`game_feature_code` 本阶段只读记录。
- 运行中的任务不得修改 `SequenceRunSnapshot`；账号变更只对下一次运行生效。
- `active bundle` 是运行时唯一真源；任务不得直接写 `daily_profiles.json` 或其他投影文件。
- 所有用户可见文本使用中文翻译资源，JSON 存储键保持稳定英文。
- 每个任务结束后必须运行对应的本地 `.venv` 测试；不回滚工作区已有的 MuMu/Android 或账号数据改动。
- 代码版本继续使用固定宽度 `X.YY.ZZ`，本系列首个实现版本为 `1.19.00`，并同步 `config.py`、AboutTab、更新日志、交接日志和标签。

---

### Task 1: 建立测试基线、数据边界和发布门禁

**Files:**
- Modify: `.gitignore`
- Modify: `.github/workflows/test.yml`
- Create: `tests/TestSecurityBaseline.py`
- Create: `tests/TestTestGroups.py`
- Modify: `run_tests.ps1`
- Modify: `更新日志.md`
- Modify: `交接/综合优化实施交接日志_2026-08-26.md`

**Interfaces:**
- Produces test groups `unit`, `integration`, `ui`, `image`, `fault_injection` and a deterministic command for each group.
- Produces `TestSecurityBaseline` checks that sensitive runtime directories are ignored and version metadata is synchronized.

- [ ] **Step 1: Write failing baseline tests**

```python
def test_runtime_data_directories_are_ignored():
    ignored = Path(".gitignore").read_text(encoding="utf-8")
    assert "config_bundle_transactions/" in ignored
    assert "config_integrity_incidents/" in ignored
    assert "账号备份/" in ignored

def test_release_metadata_uses_same_version():
    version = re.search(r'version\s*=\s*"([0-9]+\.[0-9]{2}\.[0-9]{2})"', Path("config.py").read_text()).group(1)
    assert version in Path("更新日志.md").read_text(encoding="utf-8")
    assert version in Path("custom_ok/ok/gui/about/AboutTab.py").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the baseline tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestSecurityBaseline tests.TestTestGroups
```

Expected: FAIL because the new runtime-directory rules and test-group manifest do not exist.

- [ ] **Step 3: Add ignored runtime paths and explicit test commands**

Add the generated account backup, transaction, integrity incident, Android build, and `.superpowers` paths to `.gitignore`. Update `run_tests.ps1` with named switches that run only the requested test group; keep image tests separate from deterministic tests. Update CI to run deterministic groups first and publish image failures as a separate artifact.

- [ ] **Step 4: Add the baseline handover entry**

Record the current 386-test result as the starting baseline: 29 known image `FinishedException` errors and 8 skips. State that only deterministic groups block the first hardening release.

- [ ] **Step 5: Run and commit the baseline slice**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestSecurityBaseline tests.TestTestGroups
git diff --check
git add .gitignore .github/workflows/test.yml run_tests.ps1 tests/TestSecurityBaseline.py tests/TestTestGroups.py 更新日志.md 交接/综合优化实施交接日志_2026-08-26.md
git commit -m "test: establish security and test-group baseline"
```

---

### Task 2: Make account identity fields read-only and add explicit rebind flow

**Files:**
- Modify: `src/account_config_editor.py`
- Modify: `src/gui/AccountConfigTab.py`
- Modify: `src/account_field_metadata.py`
- Modify: `src/account_identity.py`
- Create: `src/account_rebind_service.py`
- Create: `tests/TestAccountIdentityProtection.py`
- Modify: `tests/TestAccountConfigEditor.py`
- Modify: `tests/TestAccountManagementTabs.py`

**Interfaces:**
- Produces `AccountConfigEditor.locked_identity_fields` containing all seven protected fields.
- Produces `AccountRebindService.preview()` and `.rebind()`; `.rebind()` requires the current identity confirmation, checks uniqueness, creates a backup, and publishes with CAS.
- `AccountConfigTab` renders protected identity values with read-only widgets and never copies them from editable form data.

- [ ] **Step 1: Add failing protection tests**

```python
def test_all_identity_fields_are_rejected_by_backend():
    for key in ("phone", "masked_phone", "nickname", "alternate_login_name", "game_feature_code", "account_aliases"):
        draft = self.editor.load_draft(self.profile_id)
        draft.account[key] = "changed"
        with self.assertRaises(LockedProfileField):
            self.editor.save_draft(draft.scope, draft, confirmed_account_label="A1")

def test_rebind_rejects_identity_collision(self):
    with self.assertRaises(AccountIdentityError):
        self.service.rebind(self.profile_id, current_identity="old", new_identity={"masked_phone": "138****0002"})
```

- [ ] **Step 2: Run the protection tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestAccountIdentityProtection tests.TestAccountConfigEditor
```

Expected: FAIL because the current lock set omits several identity fields and no rebind service exists.

- [ ] **Step 3: Lock fields at the editor boundary**

Extend `_LOCKED_ACCOUNT` with `phone`, `masked_phone`, `nickname`, and `alternate_login_name`. Add a public immutable tuple so UI and tests use one source of truth. Keep `game_feature_code` and aliases locked. Ensure `preview_diff()` redacts identity values.

- [ ] **Step 4: Make the UI genuinely read-only**

Replace editable identity `QLineEdit` widgets with read-only fields or labels. Remove identity assignment from `_apply_text()`. Keep the UUID, masked phone, U…A name and feature code visible. Add a separate “重新绑定账号” button that opens the rebind flow and does not share the normal task-field save path.

- [ ] **Step 5: Implement explicit rebind service**

Create `AccountRebindService` using the existing repository and backup service. Validate the current identity, call `match_profile_identity()` for collision checks, require a non-empty new identity, create a transaction backup, publish through CAS, and emit an audit record containing only UUID, revision and redacted identity summaries.

- [ ] **Step 6: Run protection and UI tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestAccountIdentityProtection tests.TestAccountConfigEditor tests.TestAccountManagementTabs tests.TestAccountIdentity
```

Expected: all pass, including a test that mutating the UI draft cannot alter protected fields.

- [ ] **Step 7: Commit the identity slice**

```powershell
git add src/account_config_editor.py src/account_rebind_service.py src/account_identity.py src/account_field_metadata.py src/gui/AccountConfigTab.py tests/TestAccountIdentityProtection.py tests/TestAccountConfigEditor.py tests/TestAccountManagementTabs.py
git commit -m "security: protect account identity fields and add explicit rebind"
```

---

### Task 3: Protect backups and harden restore paths

**Files:**
- Modify: `src/config_backup.py`
- Modify: `src/account_config_bundle.py`
- Modify: `src/config_integrity.py`
- Create: `src/secure_backup.py`
- Create: `tests/TestSecureBackup.py`
- Modify: `tests/TestConfigBackup.py`
- Modify: `tests/TestConfigIntegrity.py`

**Interfaces:**
- Produces `SecureBackupService.encrypt_snapshot()` and `.decrypt_snapshot()` using Windows DPAPI on Windows and an explicit unsupported-safe-mode error elsewhere.
- Produces `validate_restore_path(source, target)` that rejects traversal, symlink escape and targets outside the configured data root.
- Existing backup and restore APIs retain their signatures while routing sensitive snapshots through the secure service.

- [ ] **Step 1: Write failing encryption and path tests**

```python
def test_sensitive_backup_is_not_plain_json(self):
    encrypted = SecureBackupService().encrypt_snapshot(b'{"phone":"13800000000"}')
    self.assertNotIn(b"13800000000", encrypted)

def test_restore_path_rejects_symlink_escape(self):
    with self.assertRaises(ValueError):
        validate_restore_path(self.backup_root / "source", self.temp_root / "outside")
```

- [ ] **Step 2: Run and verify failure**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestSecureBackup tests.TestConfigBackup tests.TestConfigIntegrity
```

Expected: FAIL because DPAPI wrapping and the centralized path validator do not exist.

- [ ] **Step 3: Implement Windows DPAPI wrapping**

Use `CryptProtectData`/`CryptUnprotectData` through `ctypes` with a versioned envelope (`format`, `scope`, `nonce`, `ciphertext`, `created_at`). Do not fall back to plaintext when DPAPI is unavailable; raise a safe-mode exception. Keep non-sensitive manifest metadata outside the encrypted payload so verification can still report corruption without decrypting.

- [ ] **Step 4: Enforce current-user permissions and restore boundaries**

Create backup directories with current-user ACLs on Windows. Validate every source, staging and target path before copying or replacing. Reject symlinked files/directories that resolve outside the expected root. Preserve the existing rollback journal and add `prepared -> verified -> activated -> mirrored` phases.

- [ ] **Step 5: Route exports and restores through the secure service**

Keep cross-device exports deliberately redacted. Local snapshots containing identity or authentication fields use DPAPI. Update bundle preflight to report “本机加密备份” versus “脱敏导出包” clearly.

- [ ] **Step 6: Run fault-injection tests**

Test interrupted copy, interrupted directory swap, corrupt encrypted payload, invalid manifest, symlink escape, and unavailable DPAPI. In every failure case assert that the old `active.json` or live config remains usable.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestSecureBackup tests.TestConfigBackup tests.TestConfigIntegrity tests.TestAccountConfigBundle
```

- [ ] **Step 7: Commit the backup slice**

```powershell
git add src/secure_backup.py src/config_backup.py src/account_config_bundle.py src/config_integrity.py tests/TestSecureBackup.py tests/TestConfigBackup.py tests/TestConfigIntegrity.py
git commit -m "security: encrypt local backups and validate restore boundaries"
```

---

### Task 4: Make active bundle publication canonical and self-reconciling

**Files:**
- Modify: `src/account_publish_service.py`
- Modify: `src/account_repository.py`
- Modify: `src/sequence_repository.py`
- Modify: `src/config_integrity.py`
- Create: `src/account_graph_store.py`
- Create: `tests/TestAccountGraphStore.py`
- Modify: `tests/TestAccountPublishService.py`
- Modify: `tests/TestAccountRepositoryRuntime.py`

**Interfaces:**
- Produces `AccountGraphStore.load_active()` and `.publish(candidate, expected_revision)` as the only runtime graph boundary.
- Produces `PublishState` values `prepared`, `verified`, `activated`, `mirrored` and recovery behavior for each state.
- Existing repository methods delegate to the graph store without changing public task-facing names.

- [ ] **Step 1: Add failing graph consistency tests**

```python
def test_runtime_reads_only_active_bundle(self):
    self.working_path.write_text("stale", encoding="utf-8")
    self.assertEqual(self.store.load_active().profiles[self.profile_id]["display_name"], "A1")

def test_interrupted_mirror_keeps_active_revision(self):
    old = self.service.load_active().revision
    with patch.object(self.store, "_mirror_projections", side_effect=OSError("interrupt")):
        with self.assertRaises(OSError):
            self.store.publish(self.candidate, expected_revision=old)
    self.assertEqual(self.service.load_active().revision, old)
```

- [ ] **Step 2: Run and verify failure**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestAccountGraphStore tests.TestAccountPublishService tests.TestAccountRepositoryRuntime
```

Expected: FAIL because runtime graph publication is spread across repository and bundle helpers.

- [ ] **Step 3: Implement the graph store boundary**

Move candidate validation, revision calculation, manifest creation, atomic pointer replacement and projection mirroring into `AccountGraphStore`. The store must write a complete staging tree before activation and must never mutate the active pointer during projection failure.

- [ ] **Step 4: Add stateful transaction recovery**

Persist the publication phase beside the staging bundle. On startup, recover only a verified complete bundle; otherwise discard staging and retain the old active revision. Validate manifest schema, all file hashes, profile UUIDs, sequence references and identity uniqueness before activation.

- [ ] **Step 5: Adapt repository and sequence callers**

Update `AccountRepository` and `SequenceRepository` to call the graph store. Keep detached projections for legacy UI compatibility, but mark them read-only copies. Remove direct task writes to legacy JSON files and add a test that monkeypatches direct writes to fail.

- [ ] **Step 6: Run migration and publication regression tests**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestAccountGraphStore tests.TestAccountPublishService tests.TestAccountRepositoryRuntime tests.TestSequenceRepository tests.TestAccountConfigBundle tests.TestAccountDeletion
```

- [ ] **Step 7: Commit the publication slice**

```powershell
git add src/account_graph_store.py src/account_publish_service.py src/account_repository.py src/sequence_repository.py src/config_integrity.py tests/TestAccountGraphStore.py tests/TestAccountPublishService.py tests/TestAccountRepositoryRuntime.py
git commit -m "refactor: make active account bundle the runtime source"
```

---

### Task 5: Extract account selection, snapshots and task coordination

**Files:**
- Create: `src/runtime/account_selection_service.py`
- Create: `src/runtime/sequence_snapshot_service.py`
- Create: `src/runtime/login_flow_service.py`
- Create: `src/runtime/task_run_coordinator.py`
- Create: `src/runtime/task_status_model.py`
- Modify: `src/task/DailyTask.py`
- Modify: `src/task/MultiAccountDailyTask.py`
- Modify: `src/task/TestAccountSwitchTask.py`
- Modify: `custom_ok/ok/gui/MainWindow.py`
- Create: `tests/TestRuntimeServices.py`
- Modify: `tests/TestAccountRuntimeIntegration.py`
- Modify: `tests/TestAccountSwitchEvidence.py`

**Interfaces:**
- `AccountSelectionService.resolve(observed, profiles) -> profile_id` rejects ambiguity and prioritizes masked phone.
- `SequenceSnapshotService.create(sequence_id) -> SequenceRunSnapshot` returns a deeply frozen snapshot.
- `TaskRunCoordinator.start(snapshot)`, `.request_stop()`, `.state` centralize start/stop/timeout transitions.
- `TaskStatusModel` exposes `phase`, `profile_id`, `sequence_id`, `revision`, `run_id`, and redacted error text.

- [ ] **Step 1: Write contract tests with fake repositories and devices**

```python
def test_selection_priority_and_ambiguity(self):
    self.assertEqual(self.selection.resolve("138****0001", self.profiles), self.a1)
    with self.assertRaises(AccountIdentityError):
        self.selection.resolve("A1", {"A1": {}, "A2": {"account_aliases": ["A1"]}})

def test_stop_does_not_mutate_snapshot(self):
    snapshot = self.snapshots.create("序列1")
    self.coordinator.request_stop()
    self.assertEqual(snapshot.profile_ids, (self.a1, self.a3))
```

- [ ] **Step 2: Run and verify failure**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestRuntimeServices tests.TestAccountRuntimeIntegration tests.TestAccountSwitchEvidence
```

Expected: FAIL because the service modules and coordinator state machine do not exist.

- [ ] **Step 3: Implement services as compatibility wrappers**

Reuse `src/account_identity.py`, `SequenceRepository`, and existing MultiAccount login methods. Do not change OCR templates or click coordinates. Wrap existing methods first, then move logic only after the service contract tests pass.

- [ ] **Step 4: Route task entry points through immutable snapshots**

Change `DailyTask`, `MultiAccountDailyTask`, and `TestAccountSwitchTask` to request a snapshot at run start. Keep `AccountChangeEvent` refresh behavior, but have running tasks record pending refreshes in the coordinator instead of mutating config widgets or run data.

- [ ] **Step 5: Add explicit lifecycle and emergency stop states**

Implement `idle`, `preflight`, `ready`, `running`, `stopping`, `stopped`, and `failed`. Ensure every stop path releases held keys/mouse buttons and persists a redacted status event. A timeout must transition to `stopping` before reporting failure.

- [ ] **Step 6: Run runtime regression tests**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestRuntimeServices tests.TestAccountRuntimeIntegration tests.TestAccountSwitchEvidence tests.TestAccountSwitch tests.TestMultiAccountDailyTask
```

- [ ] **Step 7: Commit the runtime slice**

```powershell
git add src/runtime src/task/DailyTask.py src/task/MultiAccountDailyTask.py src/task/TestAccountSwitchTask.py custom_ok/ok/gui/MainWindow.py tests/TestRuntimeServices.py tests/TestAccountRuntimeIntegration.py tests/TestAccountSwitchEvidence.py
git commit -m "refactor: isolate account selection and task run coordination"
```

---

### Task 6: Improve the five-page UI without exposing internal complexity

**Files:**
- Modify: `src/gui/AccountConfigTab.py`
- Modify: `src/gui/SequenceManagementTab.py`
- Modify: `src/gui/AccountSettingsTab.py`
- Modify: `src/gui/TaskHubTab.py`
- Modify: `src/gui/TestHubTab.py`
- Modify: `src/gui/SectionPanel.py`
- Modify: `src/gui/FlatSettingRow.py`
- Modify: `src/gui/CodexTheme.py`
- Modify: `custom_ok/ok/gui/MainWindow.py`
- Modify: `custom_ok/ok/gui/settings/SettingTab.py`
- Create: `src/gui/AccountFilterBar.py`
- Create: `tests/TestUsabilityUI.py`
- Modify: `tests/TestCodexLightUI.py`
- Modify: `tests/TestAccountManagementTabs.py`

**Interfaces:**
- `AccountFilterBar` emits `filter_changed(text, sequence_id, incomplete_only)`.
- `AccountConfigTab` exposes `dirty`, `selected_profile_id`, `show_redacted_diff()` and `reset_task_field(key)`.
- `SequenceManagementTab` exposes `selected_sequence_id`, drag/drop reorder and member display records.
- Task cards display snapshot identity and status through `TaskStatusModel`.

- [ ] **Step 1: Write failing UI behavior tests**

```python
def test_identity_widgets_are_read_only(self):
    tab = build_account_tab_with_fake_repository()
    for widget in tab.identity_widgets.values():
        self.assertTrue(widget.isReadOnly() or not widget.isEnabled())

def test_filter_keeps_only_matching_accounts(self):
    bar = AccountFilterBar()
    bar.set_text("A3")
    self.assertEqual(bar.current_filter.text, "A3")
```

- [ ] **Step 2: Run and verify failure**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestUsabilityUI tests.TestCodexLightUI tests.TestAccountManagementTabs
```

Expected: FAIL because filtering, dirty state, read-only identity controls and member drag/drop are not implemented.

- [ ] **Step 3: Implement account usability controls**

Add a fixed summary header with short name, masked phone, U…A name, sequence memberships and revision. Add search/sequence/incomplete filters, dirty-state indicator, per-field reset and a collapsed advanced JSON editor. Keep the existing diff preview and sanitize all displayed errors.

- [ ] **Step 4: Implement sequence usability controls**

Show member short name, masked phone, alternate name and enabled state. Add drag/drop reorder with the existing repository publish path. Display task references before deletion and keep the existing second confirmation.

- [ ] **Step 5: Improve task/test pages and status surfaces**

Add current sequence/account/revision labels, disable conflicting controls while running, and expose “打开日志” plus “复制脱敏诊断”. Keep logs out of the task page. Add a clear safe-mode banner with check, restore and retry actions.

- [ ] **Step 6: Complete localization and theme consistency**

Move remaining user-facing English strings into the existing gettext catalog. Keep storage keys unchanged. Extend Codex light tokens to error, disabled, focus and warning states and verify minimum contrast for labels and buttons.

- [ ] **Step 7: Run UI tests**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestUsabilityUI tests.TestCodexLightUI tests.TestAccountManagementTabs tests.TestFiveSectionMainWindow tests.TestNavigationSections tests.TestTaskNavigationClassification
```

- [ ] **Step 8: Commit the UI slice**

```powershell
git add src/gui custom_ok/ok/gui/MainWindow.py custom_ok/ok/gui/settings/SettingTab.py tests/TestUsabilityUI.py tests/TestCodexLightUI.py tests/TestAccountManagementTabs.py tests/TestFiveSectionMainWindow.py
git commit -m "feat: simplify account sequence and task workflows"
```

---

### Task 7: Replace silent failures with safe observability

**Files:**
- Modify: `main.py`
- Modify: `custom_ok/ok/gui/MainWindow.py`
- Modify: `src/config_integrity.py`
- Modify: `src/config_backup.py`
- Modify: `src/account_config_bundle.py`
- Modify: `src/task/DailyTask.py`
- Modify: `src/task/MultiAccountDailyTask.py`
- Create: `src/observability.py`
- Create: `tests/TestObservability.py`

**Interfaces:**
- `CorrelationContext.new(operation, profile_id=None, revision=None, run_id=None)` returns a context manager.
- `redact_message(value)` removes full phone numbers, tokens, cookies and login URLs.
- `StartupFailure` and `SafeModeReason` provide user-facing summaries without exposing raw exceptions.

- [ ] **Step 1: Write failing redaction and failure-surface tests**

```python
def test_redaction_removes_credentials(self):
    text = redact_message("phone=13800000000 token=abcdefghijklmnopqrstuvwxyz0123456789")
    self.assertNotIn("13800000000", text)
    self.assertNotIn("abcdefghijklmnopqrstuvwxyz0123456789", text)

def test_refresh_failure_is_reported(self):
    result = safe_call("account refresh", lambda: 1 / 0)
    self.assertEqual(result.state, "failed")
    self.assertTrue(result.user_message)
```

- [ ] **Step 2: Run and verify failure**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestObservability
```

Expected: FAIL because the shared redaction and failure result types do not exist.

- [ ] **Step 3: Add structured context and redaction**

Implement operation, revision, run_id and profile UUID fields. Use the existing redaction rules from account bundle export as the single shared implementation. Keep full sensitive values out of exception messages before they reach the logger.

- [ ] **Step 4: Replace silent exception swallowing at boundaries**

Update startup synchronization, account refresh, import/restore, and task start boundaries to log a typed failure and show a safe UI status. Preserve best-effort cleanup only where failure cannot affect account correctness, and add comments explaining that boundary.

- [ ] **Step 5: Add diagnostics actions**

Add a sanitized diagnostic export and log-open action to program settings. The diagnostic package contains version, OS, selected backend, last safe-mode reason and redacted stack summaries; it excludes account identity values and credentials.

- [ ] **Step 6: Run observability tests**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestObservability tests.TestConfigIntegrity tests.TestConfigBackup tests.TestAccountConfigBundle tests.TestMainWindowStartup
```

- [ ] **Step 7: Commit the observability slice**

```powershell
git add main.py custom_ok/ok/gui/MainWindow.py src/observability.py src/config_integrity.py src/config_backup.py src/account_config_bundle.py src/task/DailyTask.py src/task/MultiAccountDailyTask.py tests/TestObservability.py
git commit -m "refactor: make failures visible without leaking account data"
```

---

### Task 8: Integrate, migrate, verify and release

**Files:**
- Modify: `config.py`
- Modify: `custom_ok/ok/gui/about/AboutTab.py`
- Modify: `更新日志.md`
- Create: `交接/综合优化实施交接日志_2026-08-26.md`
- Modify: `.github/workflows/test.yml`
- Modify: `.github/workflows/build.yml`
- Modify: `docs/references/account-profile-security-references.md`
- Modify: `docs/references/pc-account-configuration-and-sequences.md`
- Create: `tests/TestReleaseReadiness.py`

**Interfaces:**
- Produces release version `1.19.00` and synchronized release notes.
- Produces a release-readiness test that checks schema migration, metadata synchronization, deterministic tests and clean tracked data boundaries.

- [ ] **Step 1: Write failing release-readiness tests**

```python
def test_version_and_release_notes_are_synchronized(self):
    version = read_config_version()
    self.assertIn(version, Path("更新日志.md").read_text(encoding="utf-8"))
    self.assertIn(version, Path("custom_ok/ok/gui/about/AboutTab.py").read_text(encoding="utf-8"))

def test_active_bundle_round_trip_after_migration(self):
    migrated = migrate_fixture("legacy_daily_profiles.json")
    self.assertTrue(AccountGraphStore.from_data(migrated).verify_ready())
```

- [ ] **Step 2: Run and verify failure**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestReleaseReadiness
```

Expected: FAIL until all previous slices and release metadata are synchronized.

- [ ] **Step 3: Run the complete deterministic suite**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "Test*.py" 2>&1 | Tee-Object full-test.log
```

Record deterministic failures separately from image failures. No core account, backup, runtime or UI test may be classified as baseline.

- [ ] **Step 4: Run static and packaging checks**

```powershell
.\.venv\Scripts\python.exe -m compileall -q src custom_ok tests
git diff --check
.\.venv\Scripts\python.exe -m mkdocs build --strict
```

- [ ] **Step 5: Perform manual acceptance**

1. Open account settings and confirm all identity fields are read-only.
2. Move A1 from sequence1 to sequence2 and verify account, sequence, task and test pages update immediately.
3. Start a task, change account settings, and verify the current run keeps the original snapshot.
4. Interrupt a backup/publish operation and verify the previous active revision remains usable.
5. Trigger ambiguous identity, invalid restore path and corrupted snapshot cases and verify safe-mode messages are actionable.
6. Confirm “打开日志” and diagnostic export contain no full phone numbers or credentials.

- [ ] **Step 6: Update release metadata and handover**

Set `config.py` to `1.19.00`. Add the same version and the seven hardening slices to AboutTab, `更新日志.md`, both reference files and the handover log. Include test counts, known image-only failures and manual acceptance results.

- [ ] **Step 7: Run release-readiness tests and commit**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestReleaseReadiness tests.TestSecurityBaseline tests.TestObservability
git add config.py custom_ok/ok/gui/about/AboutTab.py 更新日志.md 交接/综合优化实施交接日志_2026-08-26.md .github/workflows/test.yml .github/workflows/build.yml docs/references/account-profile-security-references.md docs/references/pc-account-configuration-and-sequences.md tests/TestReleaseReadiness.py
git commit -m "release: harden account safety and usability in v1.19.00"
```

- [ ] **Step 8: Tag and publish after verification**

```powershell
git tag -a v1.19.00 -m "Release v1.19.00: comprehensive safety and usability hardening"
git push origin master
git push origin v1.19.00
```

If the remote is unavailable, retain the local commit and tag, record the failure in the handover log, and retry only after connectivity is restored.

## Final self-review checklist

- [ ] No task writes mutable account JSON directly.
- [ ] No ordinary account edit can change a protected identity field.
- [ ] DPAPI failure cannot silently downgrade to plaintext backup.
- [ ] Restore path validation rejects traversal and symlink escape.
- [ ] Active bundle remains usable after interrupted publication.
- [ ] Running snapshots remain immutable after UI changes.
- [ ] UI displays safe status without embedding a log console.
- [ ] Deterministic tests and image tests are reported separately.
- [ ] Version, release notes, handover, references and tag match exactly.
