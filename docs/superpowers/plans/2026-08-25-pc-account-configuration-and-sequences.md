# PC Account Configuration and Sequences Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Execute this plan task-by-task in the current root session; this repository forbids subagent delegation unless the user explicitly requests it. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe PC-side account editing, standalone sequence management, shared identity resolution, immutable run snapshots, and a migration assessment without importing Android code.

**Architecture:** Keep the existing integrity service and account master as the authority. Add focused identity, editor, and sequence facades; GUI calls those services, while production and test switching consume one immutable snapshot API.

**Tech Stack:** Python 3.12, PySide6/qfluentwidgets, JSON, unittest, repository-local `.venv`.

**Spec:** `docs/superpowers/specs/2026-08-25-pc-account-configuration-and-sequences-design.md`

## Global Constraints

- PC-only: do not add Android, MuMu, ADB, Combat Agent, device binding, installer, or diagnostic-transfer code.
- Preserve all pre-existing dirty-worktree changes and adapt to them.
- Never log or display complete phone numbers, passwords, tokens, or alternate login identities.
- `TestAccountSwitchTask` must reuse the production switching path.
- Code changes require version `1.09.00`, synchronized product update text, changelog, handoff log, and references.
- Use `E:\AI work\ok-wuthering-waves-master\.venv\Scripts\python.exe` for tests when present.

---

### Task 1: Shared Account Identity Resolver

**Files:**
- Create: `src/account_identity.py`
- Modify: `src/config_integrity.py`
- Modify: `src/task/MultiAccountDailyTask.py`
- Modify: `src/task/TestAccountSwitchTask.py`
- Test: `tests/TestAccountIdentity.py`
- Test: `tests/TestMultiAccountDailyTask.py`

**Interfaces:**
- Produces: `normalize_identity`, `split_identity_values`, `masked_phone`, `short_profile_name`, `profile_identity_values`, `resolve_profile_identity`, `resolve_profile_short_names`.
- Consumers: integrity matching, production account matching, focused switch test.

- [ ] Write failing tests for exact A1/A10 matching, aliases, masked/full-phone candidates, duplicate short names, duplicate identities, missing names, and redacted exceptions.
- [ ] Run `python -m unittest tests.TestAccountIdentity tests.TestMultiAccountDailyTask` and confirm the new module/tests fail before implementation.
- [ ] Port the minimal pure functions from the archived branch; preserve compatibility wrappers in existing modules.
- [ ] Replace duplicate production and integrity logic with imports from the shared module.
- [ ] Run identity, integrity, production-switch, and focused-switch tests.

### Task 2: Safe Single-Account Editor and GUI

**Files:**
- Create: `src/account_config_editor.py`
- Create: `src/gui/AccountConfigTab.py`
- Modify: `src/account_repository.py`
- Modify: `src/gui/__init__.py`
- Modify: `config.py`
- Test: `tests/TestAccountConfigEditor.py`
- Test: `tests/TestAccountConfigTab.py`
- Test: `tests/TestAccountRepositoryRuntime.py`

**Interfaces:**
- Consumes: existing account master/integrity service, `AccountRepository`, `ConfigBackupService`, shared masking.
- Produces: `ProfileEditScope`, `ProfileDraft`, `ProfileDiff`, `AccountConfigEditor.load_draft`, `preview_diff`, `save_draft`, and `AccountConfigTab`.

- [ ] Write failing service tests for draft isolation, locked UUID/login fields, diff masking, backup-before-write, atomic save, and stale-revision rejection.
- [ ] Extend the existing repository only with the narrow read/edit methods required by the editor; reuse its atomic writer and current on-disk layout.
- [ ] Implement editor validation and saving without external-accept/restore workflow.
- [ ] Write GUI tests for account selection, editable-field allowlist, read-only metadata, draft discard, and confirmed save.
- [ ] Implement the custom tab and register it after default tabs.
- [ ] Run editor, repository, integrity, backup, bundle, and GUI startup tests.

### Task 3: Standalone Sequence Repository and Management Tab

**Files:**
- Create: `src/sequence_repository.py`
- Create: `src/gui/SequenceManagementTab.py`
- Modify: `src/task/MultiAccountDailyTask.py`
- Modify: `src/gui/__init__.py`
- Modify: `config.py`
- Test: `tests/TestSequenceRepository.py`
- Test: `tests/TestSequenceManagementTab.py`
- Test: `tests/TestMultiAccountDailyTask.py`

**Interfaces:**
- Consumes: `AccountRepository`, shared identity resolver, existing `daily_profiles.json` sequence projection.
- Produces: `SequenceEditScope`, `SequenceDraft`, `SequenceDiff`, CRUD/reorder validation, account-reference guard, `SequenceManagementTab`.

- [ ] Write failing tests for create/copy/rename/enable/delete, add/remove/reorder, duplicate and missing members, stale revisions, delete protection, and legacy sequence reads.
- [ ] Implement the smallest sequence facade backed by the existing authority; do not add device rules.
- [ ] Write GUI tests for sequence actions and redacted account display.
- [ ] Implement and register the management tab.
- [ ] Remove the embedded Qt dialog and direct JSON writes from `MultiAccountDailyTask`, retaining compatibility callbacks that delegate to the service/tab.
- [ ] Run sequence, multi-account, account repository, integrity, bundle, and GUI startup tests.

### Task 4: Immutable Run Snapshots

**Files:**
- Modify: `src/sequence_repository.py`
- Modify: `src/task/MultiAccountDailyTask.py`
- Modify: `src/task/TestAccountSwitchTask.py`
- Test: `tests/TestSequenceRepository.py`
- Test: `tests/TestMultiAccountDailyTask.py`
- Test: `tests/TestAccountSwitch.py`

**Interfaces:**
- Produces: frozen `SequenceRunSnapshot(sequence_id, revision, profile_ids, profiles, run_id)` and `create_run_snapshot`/`snapshot_for_profile_ids`.
- Consumers: production and focused test tasks.

- [ ] Write failing tests proving later file/UI changes do not alter an active snapshot and both task entry points use the same snapshot constructor.
- [ ] Implement deep-copied frozen snapshots with a UUID run ID and source fingerprints.
- [ ] Update production execution to resolve the sequence once at task start.
- [ ] Update focused switching to request the production snapshot path rather than maintain a parallel order implementation.
- [ ] Run production/test switching and account runtime integration tests.

### Task 5: Per-Account Directory Migration Assessment

**Files:**
- Create: `src/account_directory_assessment.py`
- Create: `tests/TestAccountDirectoryAssessment.py`
- Create: `docs/account-directory-migration-assessment.md`

**Interfaces:**
- Produces: pure `project_account_layout(master)`, `round_trip_projection(master)`, and `assess_account_directory_migration(master)`; performs no production writes.

- [ ] Write failing temporary-directory/pure-data tests for field mapping, round trip, duplicate identity, unsupported field, and rollback findings.
- [ ] Implement a read-only assessment that returns structured blockers/warnings and projected filenames without touching real config.
- [ ] Document account/task/accepted-summary boundaries, compatibility, rollback, bundle/backup impacts, and a no-go/go decision.
- [ ] Run assessment, integrity, bundle, and backup tests.

### Task 6: Documentation, Version, and Release Verification

**Files:**
- Modify: `config.py`
- Modify: `custom_ok/ok/gui/about/AboutTab.py`
- Modify: `更新日志.md`
- Create: `交接/PC账号配置与序列管理交接日志_2026-08-25.md`
- Create: `docs/references/pc-account-configuration-and-sequences.md`

**Interfaces:**
- Documents all new public APIs, decisions, test evidence, remaining risks, and source provenance.

- [ ] Update `config.py` to `1.09.00` and add matching user-facing update text.
- [ ] Add a changelog entry covering shared identities, safe editor, standalone sequences, immutable snapshots, and migration assessment.
- [ ] Write the handoff log with changed files, data authority, recovery notes, test commands/results, and known limitations.
- [ ] Write references citing the archived local implementation files, current repository modules, Python/PySide6/Qt documentation, and security principles used; distinguish local design sources from external references.
- [ ] Run `py_compile` on changed Python files.
- [ ] Run all focused account/config/sequence/switch/GUI tests, then the repository test suite.
- [ ] Review `git diff --check`, status, version text, and ensure no Android code entered the change.
- [ ] Commit only task-owned files, create annotated `v1.09.00`, and push branch/tag per repository policy if all verification passes.

