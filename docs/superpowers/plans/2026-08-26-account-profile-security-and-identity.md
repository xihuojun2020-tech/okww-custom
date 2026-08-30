# Account Profile Security and Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safely editable per-account JSON profiles with atomic published snapshots, UUID isolation, masked-phone-first switching, and a reserved future game-feature-code check.

**Architecture:** User edits are stored as one JSON file per UUID profile plus an index containing sequence membership. A publish service validates the complete graph, creates an immutable revision bundle with a SHA-256 manifest, and atomically advances a small active pointer; tasks read only the active snapshot while runtime progress remains UUID-keyed and separate. The existing master/working files remain generated compatibility projections until all consumers use the active snapshot.

**Tech Stack:** Python 3, existing `pathlib`/`json`/`hashlib`/`tempfile` atomic helpers, PySide6 UI, unittest/pytest-compatible test suite, local `.venv` interpreter.

**Spec:** `docs/superpowers/specs/2026-08-26-account-profile-security-and-identity-design.md`

## Global Constraints

- Preserve the immutable internal `profile_id` UUID; display names, phones, masked phones, nicknames, and U…A names are never sequence foreign keys.
- `masked_phone` is the current account-switching key; `alternate_login_name` is a fallback candidate; `game_feature_code` is stored only and must not affect current tasks.
- Runtime state is UUID-keyed and cannot write stable account profiles, the account index, or a published bundle.
- Every multi-file publication must validate first, write a complete temporary bundle, compute SHA-256 manifest entries, then atomically replace `active.json`.
- A stale editor revision must raise `ProfileRevisionConflict`; no last-writer-wins overwrite is allowed.
- Full phone numbers and credentials are excluded from ordinary logs and redacted in previews/export diagnostics.
- Use `.\.venv\Scripts\python.exe` for Python commands when that interpreter exists.
- The release containing code changes must update `config.py` from `1.16.01` to `1.17.00`, synchronize product-facing release text, and create the matching annotated tag after verification.

---

### Task 1: Formalize the three identity fields and matching precedence

**Files:**
- Modify: `src/account_identity.py`
- Modify: `src/config_integrity.py` (`_profile_identity_values`, validation/normalization helpers)
- Modify: `src/account_config_bundle.py` (`_validate_bundle_shapes`, redaction rules)
- Test: `tests/TestAccountIdentity.py`
- Test: `tests/TestConfigIntegrity.py`
- Test: `tests/TestAccountConfigBundle.py`

**Interfaces:**
- Produce `AccountIdentity` (frozen dataclass) with `profile_id`, `phone`, `masked_phone`, `nickname`, `display_name`, `alternate_login_name`, and `game_feature_code` fields.
- Produce `extract_account_identity(profile_id: str, profile: Mapping[str, Any]) -> AccountIdentity`.
- Preserve `resolve_profile_identity(observed, profiles)` for existing callers and add `match_profile_identity(observed, profiles, *, strict_feature_code: bool = False) -> str | None`.
- Matching order is exact `masked_phone` first, then nickname/full phone for disambiguation, then U…A alternate name; `game_feature_code` is considered only when `strict_feature_code=True`.

- [ ] **Step 1: Write failing identity tests**

```python
def test_masked_phone_is_preserved_and_matches_first():
    profiles = {
        "p-a1": {
            "profile_id": "p-a1",
            "display_name": "A1",
            "masked_phone": "199****0002",
            "nickname": "夜归",
            "alternate_login_name": "UTEST0001A",
        }
    }
    assert resolve_profile_identity("199****0002", profiles) == "p-a1"
    identity = extract_account_identity("p-a1", profiles["p-a1"])
    assert identity.masked_phone == "199****0002"
```

- [ ] **Step 2: Run the focused tests and verify the missing-field failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestAccountIdentity.py -q`

Expected: the new test fails because `masked_phone` is not yet a first-class field.

- [ ] **Step 3: Implement normalized extraction and precedence without breaking legacy aliases**

Keep existing short-name and legacy `备用识别名称内容` parsing. Add explicit `masked_phone` and `alternate_login_name` sources, preserve the literal masked value, and raise `AccountIdentityError` when two profiles share the same decisive candidate.

- [ ] **Step 4: Add schema validation and safe bundle handling**

Validate identity fields as strings when present, preserve `_comments`/`extensions`, and redact only complete phone/credential values in diagnostics; never replace or delete `masked_phone` during import/export.

- [ ] **Step 5: Run identity, integrity, and bundle tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestAccountIdentity.py tests/TestConfigIntegrity.py tests/TestAccountConfigBundle.py -q`

Expected: all existing tests plus the new masked-phone and feature-code opt-in tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/account_identity.py src/config_integrity.py src/account_config_bundle.py tests/TestAccountIdentity.py tests/TestConfigIntegrity.py tests/TestAccountConfigBundle.py
git commit -m "feat: formalize account identity fields"
```

### Task 2: Add the editable per-account store and index projection

**Files:**
- Create: `src/account_profile_store.py`
- Modify: `src/account_repository.py`
- Modify: `src/config_integrity.py` (`ConfigPaths`, account-directory validation)
- Test: `tests/TestAccountProfileStore.py`
- Test: `tests/TestAccountRepositoryRuntime.py`
- Test: `tests/TestAccountDirectoryAssessment.py`

**Interfaces:**
- Produce `EditableProfile(profile_id: str, revision: str, payload: Mapping[str, Any])` and `AccountProfileStore(root: Path | str)` with `load_index() -> dict`, `load_profile(profile_id) -> EditableProfile`, `write_profile(profile_id, payload, expected_revision) -> str`, `write_index(payload, expected_revision) -> str`, and `list_profile_ids() -> tuple[str, ...]`.
- `AccountRepository` remains the UI/task facade and delegates stable-file writes to this store; existing `load_profile`, `publish_profile`, `publish_sequence`, and deletion method signatures remain compatible.
- Store paths are `configs/accounts/profiles/<UUID>.json`, `configs/accounts/index.json`, and `configs/accounts/sequences.json`; all stable writes use the existing atomic JSON helper.

The test-only `seed_for_test()` helper writes a two-profile graph with UUID-like IDs `p-a1` and `p-a3` into a temporary store; production code must not expose that helper.

- [ ] **Step 1: Write failing isolation and revision tests**

```python
def test_editing_a1_does_not_change_a3(tmp_path):
    store = AccountProfileStore(tmp_path)
    store.seed_for_test({"p-a1": {"display_name": "A1"}, "p-a3": {"display_name": "A3"}})
    revision = store.load_profile("p-a1").revision
    store.write_profile("p-a1", {"display_name": "A1-new"}, revision)
    assert store.load_profile("p-a3").payload["display_name"] == "A3"

def test_stale_profile_edit_is_rejected(tmp_path):
    store = AccountProfileStore(tmp_path)
    first = store.load_profile("p-a1").revision
    store.write_profile("p-a1", {"display_name": "first"}, first)
    with pytest.raises(ProfileRevisionConflict):
        store.write_profile("p-a1", {"display_name": "stale"}, first)
```

- [ ] **Step 2: Run the new store tests and verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestAccountProfileStore.py -q`

Expected: import or method failures because the per-account store does not exist.

- [ ] **Step 3: Implement UUID-file storage and deterministic revisions**

Reject non-UUID filenames, reject a payload whose embedded `profile_id` differs from the path, preserve unknown fields, calculate revisions from canonical JSON, and write only the target profile file for profile edits.

- [ ] **Step 4: Make repository reads and legacy projection use the store**

Keep `account_master_config.json` as a compatibility projection during migration. `legacy_profile_projection()` must include `masked_phone`, `alternate_login_name`, and `game_feature_code` without converting them into display names.

- [ ] **Step 5: Test sequences and runtime isolation**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestAccountRepositoryRuntime.py tests/TestAccountDirectoryAssessment.py tests/TestSequenceRepository.py -q`

Expected: sequence membership remains UUID-keyed and runtime writes do not alter profile JSON bytes.

- [ ] **Step 6: Commit**

```bash
git add src/account_profile_store.py src/account_repository.py src/config_integrity.py tests/TestAccountProfileStore.py tests/TestAccountRepositoryRuntime.py tests/TestAccountDirectoryAssessment.py
git commit -m "feat: add isolated account profile store"
```

### Task 3: Implement immutable published bundles and crash-safe activation

**Files:**
- Create: `src/account_publish_service.py`
- Modify: `src/account_config_bundle.py`
- Modify: `src/config_integrity.py`
- Test: `tests/TestAccountPublishService.py`
- Test: `tests/TestConfigBackup.py`
- Test: `tests/TestConfigIntegrity.py`

**Interfaces:**
- Produce `PublishedRevision(revision: str, bundle_dir: Path, manifest: Mapping[str, Any])`.
- Produce `AccountPublishService.publish(*, expected_revision: str, profiles: Mapping[str, Any], index: Mapping[str, Any], sequences: Mapping[str, list[str]]) -> PublishedRevision`.
- Produce `load_active() -> PublishedRevision` and `recover_incomplete_transactions() -> None`.
- `ConfigIntegrityService` gains `check_active_bundle()` and continues exposing the existing `check()` during compatibility mode.

Test fixtures used by this task are concrete UUID-keyed mappings:

```python
PROFILES = {"p-a1": {"profile_id": "p-a1", "display_name": "A1"}}
INDEX = {"profile_ids": ["p-a1"]}
SEQUENCES = {"序列一": ["p-a1"]}
UPDATED_PROFILES = {"p-a1": {"profile_id": "p-a1", "display_name": "A1-new"}}
```

- [ ] **Step 1: Write failing manifest and crash-recovery tests**

```python
def test_publish_changes_active_pointer_only_after_manifest_valid(tmp_path):
    service = AccountPublishService(tmp_path)
    revision = service.publish(expected_revision="", profiles=PROFILES, index=INDEX, sequences=SEQUENCES)
    assert service.load_active().revision == revision.revision
    assert service.load_active().manifest["files"]["p-a1.json"]["sha256"]

def test_interrupted_publish_keeps_previous_active_bundle(tmp_path):
    service = AccountPublishService(tmp_path, fail_after_bundle_write=True)
    old = service.publish(expected_revision="", profiles=PROFILES, index=INDEX, sequences=SEQUENCES)
    with pytest.raises(RuntimeError):
        service.publish(expected_revision=old.revision, profiles=UPDATED_PROFILES, index=INDEX, sequences=SEQUENCES)
    assert service.load_active().revision == old.revision
```

- [ ] **Step 2: Run focused tests and verify the service is missing**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestAccountPublishService.py -q`

Expected: collection fails because `src.account_publish_service` is not present.

- [ ] **Step 3: Write complete revision directories before replacing `active.json`**

Create `published/bundles/<revision>/account_master_config.json`, `daily_profiles.json`, and `manifest.json`; fsync each file; include per-file SHA-256, schema version, program version, and source revision; then atomically replace `published/active.json`.

- [ ] **Step 4: Add cross-process lock, backup, and startup recovery**

Use an OS-level lock file around publication, retain the previous active revision in `backups`, quarantine incomplete bundle directories, and never delete the active bundle during cleanup.

- [ ] **Step 5: Route bundle import/export through the service**

Preserve the existing redaction and preflight behavior in `AccountConfigBundleService`, but make confirmed imports publish a new revision instead of replacing several live files independently.

- [ ] **Step 6: Run integrity and backup fault tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestAccountPublishService.py tests/TestConfigIntegrity.py tests/TestConfigBackup.py tests/TestAccountConfigBundle.py -q`

Expected: old and new revisions are always complete; forced termination leaves either the old or new active pointer.

- [ ] **Step 7: Commit**

```bash
git add src/account_publish_service.py src/account_config_bundle.py src/config_integrity.py tests/TestAccountPublishService.py tests/TestConfigBackup.py tests/TestConfigIntegrity.py
git commit -m "feat: publish crash-safe account bundles"
```

### Task 4: Add safe account and sequence editing UI

**Files:**
- Modify: `src/gui/AccountConfigTab.py`
- Modify: `src/gui/AccountSettingsTab.py`
- Modify: `src/gui/SequenceManagementTab.py`
- Modify: `src/gui/DailyProfileDialog.py`
- Modify: `src/account_config_editor.py`
- Test: `tests/TestAccountConfigEditor.py`
- Test: `tests/TestAccountManagementTabs.py`
- Test: `tests/TestAccountDeletion.py`

**Interfaces:**
- `AccountConfigEditor.load_draft(profile_id) -> ProfileDraft` includes all three identity layers.
- `preview_diff(draft) -> ProfileDiff` redacts full phone values but shows `masked_phone`.
- `save_draft(scope, draft, confirmed_account_label, sequence_ids) -> ProfileRecord` publishes through `AccountRepository` and `AccountPublishService`.
- `delete_profile(scope, confirmed_account_label) -> AccountDeletionPreview` remains a two-step, recoverable operation.

Each editor test creates `repository = AccountRepository(tmp_path)` and `editor = AccountConfigEditor(repository)` against a fixture containing A1 with `masked_phone="199****0002"` and full phone `"19910000001"`.

- [ ] **Step 1: Write failing UI-service tests**

```python
def test_profile_diff_keeps_masked_phone_visible_and_redacts_full_phone():
    draft = editor.load_draft("p-a1")
    draft.account["masked_phone"] = "199****0002"
    diff = editor.preview_diff(draft)
    assert "199****0002" in {entry.after for entry in diff.changes}
    assert "19910000001" not in str(diff)
```

- [ ] **Step 2: Run focused tests and verify the new identity fields are absent from the editor contract**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestAccountConfigEditor.py tests/TestAccountManagementTabs.py -q`

Expected: the new field assertions fail before UI/editor changes.

- [ ] **Step 3: Add labeled fields, help text, and read-only future feature-code display**

Show Chinese labels for phone, masked phone, nickname, U…A alternate name, and game feature code. The feature-code widget is read-only and explicitly states “当前仅记录，不参与任务”.

- [ ] **Step 4: Add diff confirmation and account-only save actions**

Ensure saving A1 sends only A1’s `profile_id` plus explicitly selected sequence IDs. Copy/import operations strip immutable identity fields until the user confirms a new UUID.

- [ ] **Step 5: Fix account and sequence deletion flows**

Account deletion shows sequence/runtime preview, requires typed display-name confirmation, backs up the account, removes only its sequence references, and refreshes both tabs. Sequence deletion removes only the sequence and its settings.

- [ ] **Step 6: Run UI and deletion tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestAccountConfigEditor.py tests/TestAccountManagementTabs.py tests/TestAccountDeletion.py tests/TestAccountFieldMetadata.py -q`

Expected: UI actions affect only the selected account or selected sequence and all confirmations produce visible success/error feedback.

- [ ] **Step 7: Commit**

```bash
git add src/gui/AccountConfigTab.py src/gui/AccountSettingsTab.py src/gui/SequenceManagementTab.py src/gui/DailyProfileDialog.py src/account_config_editor.py tests/TestAccountConfigEditor.py tests/TestAccountManagementTabs.py tests/TestAccountDeletion.py
git commit -m "feat: add safe account identity editing UI"
```

### Task 5: Connect task execution and account-switch tests to the active snapshot

**Files:**
- Modify: `src/task/MultiAccountDailyTask.py`
- Modify: `src/task/TestAccountSwitchTask.py`
- Modify: `src/sequence_repository.py`
- Modify: `src/account_switch_evidence.py`
- Test: `tests/TestMultiAccountDailyTask.py`
- Test: `tests/TestAccountSwitch.py`
- Test: `tests/TestAccountSwitchEvidence.py`

**Interfaces:**
- `MultiAccountDailyTask._load_profiles()` reads the immutable active snapshot after the integrity guard.
- `MultiAccountDailyTask.match_profile_from_login(login_text)` uses masked-phone-first matching and then U…A fallback.
- `MultiAccountDailyTask.switch_to_account(profile_name, max_retries=5)` remains the production entry point used by `TestAccountSwitchTask`.
- `SequenceRepository.snapshot_for_profile_ids()` receives UUIDs and returns a frozen run snapshot.

The `multi_task` fixture constructs `MultiAccountDailyTask` with the repository fixture from Task 2 and a sequence containing A1, A3, and A4; no emulator or game window is required for these matcher tests.

- [ ] **Step 1: Write failing switching tests for masked phone and U…A fallback**

```python
def test_switch_matching_prefers_masked_phone(multi_task):
    assert multi_task.match_profile_from_login("199****0002") == "A1"

def test_switch_matching_uses_u_name_when_masked_phone_is_unavailable(multi_task):
    assert multi_task.match_profile_from_login("UTEST0001A") == "A1"
```

- [ ] **Step 2: Run the focused account-switch suite and verify active-snapshot wiring is missing**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestMultiAccountDailyTask.py tests/TestAccountSwitch.py tests/TestAccountSwitchEvidence.py -q`

Expected: the new active-snapshot and precedence assertions fail while legacy tests remain visible.

- [ ] **Step 3: Load and freeze the active bundle before task execution**

At task start, call the integrity service, obtain an immutable snapshot, resolve the selected sequence to UUIDs, and refuse to continue if the active manifest changes before a switch.

- [ ] **Step 4: Replace ad-hoc identity parsing with the shared matcher**

Remove duplicate phone/U-name matching branches from `MultiAccountDailyTask`; keep logging and evidence stages, but record the matched `profile_id`, masked phone, and matching source without writing full phone values.

- [ ] **Step 5: Keep `TestAccountSwitchTask` synchronized with production**

The test task must call `MultiAccountDailyTask.switch_to_account`, production retry/logout/login helpers, and the default A1 → A3 → A4 order while resolving exact profile IDs.

- [ ] **Step 6: Run account-switch and runtime integration tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestMultiAccountDailyTask.py tests/TestAccountSwitch.py tests/TestAccountSwitchEvidence.py tests/TestAccountRuntimeIntegration.py -q`

Expected: masked-phone matching, U…A fallback, sequence membership, retry evidence, and UUID-keyed completion records all pass.

- [ ] **Step 7: Commit**

```bash
git add src/task/MultiAccountDailyTask.py src/task/TestAccountSwitchTask.py src/sequence_repository.py src/account_switch_evidence.py tests/TestMultiAccountDailyTask.py tests/TestAccountSwitch.py tests/TestAccountSwitchEvidence.py
git commit -m "feat: run account switching from published profiles"
```

### Task 6: Migrate existing configurations and retain rollback compatibility

**Files:**
- Modify: `src/account_directory_assessment.py`
- Modify: `src/config_integrity.py`
- Modify: `src/account_config_bundle.py`
- Modify: `src/storage.py`
- Create: `tests/TestAccountProfileMigration.py`
- Modify: `docs/account-directory-migration-assessment.md`
- Modify: `docs/references/pc-account-configuration-and-sequences.md`

**Interfaces:**
- Produce `migrate_master_to_profiles(source_master, destination_root, *, confirm=False) -> MigrationReport`.
- Produce `MigrationReport` with `profile_ids`, `masked_phone_fields`, `sequence_names`, `warnings`, and `rollback_path`.
- Migration must preserve UUIDs, `masked_phone`, U…A aliases, feature codes, unknown extensions, sequence order, and runtime completion records.

`MASTER_FIXTURE` is a schema-v1 mapping with one profile containing `profile_id="p-a1"`, `masked_phone="199****0002"`, `alternate_login_name="UTEST0001A"`, `game_feature_code="FC-A1"`, and one sequence named `序列一`; `load_editable_graph(root)` reads the generated index and profile files for assertions.

- [ ] **Step 1: Write failing round-trip and conflict tests**

```python
def test_master_to_profile_files_round_trip_preserves_three_identity_layers(tmp_path):
    report = migrate_master_to_profiles(MASTER_FIXTURE, tmp_path, confirm=True)
    assert report.masked_phone_fields == 1
    restored = load_editable_graph(tmp_path)
    assert restored["profiles"]["p-a1"]["masked_phone"] == "199****0002"
    assert restored["profiles"]["p-a1"]["alternate_login_name"] == "UTEST0001A"
```

- [ ] **Step 2: Run migration tests and verify the migration entry point is absent**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestAccountProfileMigration.py -q`

Expected: collection fails until the migration service and fixture are added.

- [ ] **Step 3: Implement preflight-only migration and explicit confirmation**

Read existing master/working files, resolve legacy names through the shared identity index, reject ambiguous masked-phone or alias matches, write a complete backup before creating profile files, and never delete the source during migration.

- [ ] **Step 4: Add dual-read shadow comparison and rollback**

Compare the generated profile graph with the old normalized master, record differences in `incidents`, and keep the legacy master/working projection available until the active-snapshot task switch is enabled.

- [ ] **Step 5: Update migration and reference documentation**

Record the three identity fields, masked-phone precedence, the current version `1.16.01`, target release `1.17.00`, and the rollback command in the handoff/reference documents.

- [ ] **Step 6: Run migration and full account configuration tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestAccountProfileMigration.py tests/TestAccountSwitchEvidence.py tests/TestAccountRepositoryMigrationScenario.py tests/TestConfigIntegrity.py -q`

Expected: old configurations round-trip without identity loss and rollback restores byte-equivalent source files.

- [ ] **Step 7: Commit**

```bash
git add src/account_directory_assessment.py src/config_integrity.py src/account_config_bundle.py src/storage.py tests/TestAccountProfileMigration.py docs/account-directory-migration-assessment.md docs/references/pc-account-configuration-and-sequences.md
git commit -m "feat: migrate account profiles with rollback"
```

### Task 7: Release synchronization, documentation, and fault-injection gate

**Files:**
- Modify: `config.py` (`version = "1.17.00"`)
- Modify: `docs/README.md` and `docs/index.md`
- Create: `docs/handover/2026-08-26-account-profile-security-handover.md`
- Create: `tests/TestAccountProfileFaultInjection.py`
- Modify: `tests/TestCodexLightUI.py` or the release-version test covering the new version

**Interfaces:**
- The handover document records the active architecture, three identity fields, current feature-code non-use, migration status, test commands, and rollback steps.
- Fault tests expose `kill_after_stage` hooks for `profile_write`, `bundle_manifest`, and `active_pointer` stages.

Fault tests reuse the concrete fixtures `PROFILES = {"p-a1": {"profile_id": "p-a1", "display_name": "A1"}}`, `INDEX = {"profile_ids": ["p-a1"]}`, and `SEQUENCES = {"序列一": ["p-a1"]}`.

- [ ] **Step 1: Write failing release and fault tests**

```python
def test_release_version_is_synchronized():
    from config import version
    assert version == "1.17.00"

def test_kill_after_active_pointer_never_exposes_partial_bundle(tmp_path):
    service = AccountPublishService(tmp_path, kill_after_stage="active_pointer")
    with pytest.raises(RuntimeError):
        service.publish(expected_revision="", profiles=PROFILES, index=INDEX, sequences=SEQUENCES)
    service.recover_incomplete_transactions()
    assert service.load_active().revision
```

- [ ] **Step 2: Run release and fault tests to establish the failing baseline**

Run: `.\.venv\Scripts\python.exe -m pytest tests/TestCodexLightUI.py tests/TestAccountProfileFaultInjection.py -q`

Expected: the version assertion and new fault hooks fail before release synchronization.

- [ ] **Step 3: Synchronize version and product-facing documentation**

Set `config.py` to `1.17.00`, update the release text and handover notes, and include the exact masked-phone-first matching rule and “feature code stored only” rule.

- [ ] **Step 4: Add forced-termination and recovery tests**

Inject failures after each publication stage, restart the service, verify the active pointer resolves to a complete bundle, and assert that no A3/A4 profile bytes change when only A1 is edited.

- [ ] **Step 5: Run the complete verification suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass, including UI, account switching, migration, integrity, backup, and fault-injection coverage.

- [ ] **Step 6: Commit, tag, and publish the verified release**

```bash
git add config.py docs/README.md docs/index.md docs/handover/2026-08-26-account-profile-security-handover.md tests/TestAccountProfileFaultInjection.py tests/TestCodexLightUI.py
git commit -m "release: publish account profile security architecture"
git tag -a v1.17.00 -m "v1.17.00 account profile security and identity isolation"
git push origin master
git push origin v1.17.00
```

Do not run this release step until the full suite and manual PC account-switch test pass.
