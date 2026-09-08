# LAN NAS Product Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a verified, recoverable product-update path that publishes OK-WW packages to a LAN NAS and installs them on clients without GitHub.

**Architecture:** A publisher writes immutable versioned ZIPs and publishes `latest.json` last to an NAS directory. The personal client uses its existing authenticated SMB share by default, with pinned HTTPS optional, validates an update into `configs/update-staging`, then launches a helper which applies it after app exit and rolls back on failure.

**Tech Stack:** Python 3.12 standard library (`http.client`, `ssl`, `hashlib`, `zipfile`, `pathlib`, `subprocess`), existing PySide6/qfluentwidgets UI, unittest test harness, existing update-package verifier.

**Spec:** `docs/superpowers/specs/2026-09-08-lan-nas-update-design.md`

## Global Constraints

- Client transport is authenticated UNC/SMB by default or pinned HTTPS when explicitly configured; there is no HTTP or GitHub fallback.
- HTTPS authenticates both the TLS trust chain and configured lowercase 64-hex leaf-certificate SHA-256 fingerprint; SMB relies on existing Windows credentials and share permissions.
- Manifest limit is 65,536 bytes; package limit is 536,870,912 bytes; connect timeout is 5 seconds; total download deadline is 120 seconds.
- Accept only `stable`, schema version `1`, and a version strictly greater than the installed fixed-width `X.YY.ZZ` version.
- Never modify `configs`, `logs`, `screenshots`, diagnostics, `.venv`, `runtime`, or user custom content.
- Reject automatic application when `requirements.txt`, `requirements.in`, or the embedded framework pin differs from the installed copy.
- Do not reuse `config['update_pyappify']`; product and launcher updates remain separate.
- Add no runtime dependency.
- Code changes use the next fixed-width product version, update `更新日志.md`, pass release validation, and are committed, annotated-tagged, and pushed together.

---

## File map

- `src/update/lan_manifest.py`: strict immutable outer-manifest model and version/path validation.
- `src/update/lan_transport.py`: HTTPS GET with CA validation, certificate pinning, limits, deadlines, and atomic local download.
- `src/update/package_validation.py`: safe ZIP and embedded-manifest validation shared by client and apply helper.
- `src/update/lan_service.py`: check/download orchestration and staging request creation; never edits installed sources.
- `src/update/lan_apply.py`: standalone post-exit transactional apply, rollback, result writing, and restart.
- `src/gui/LanUpdateCard.py`: user-visible manual check/download/install workflow.
- `scripts/publish_lan_update.py`: atomic NAS publication.
- `tests/TestLanUpdateManifest.py`, `tests/TestLanUpdateTransport.py`, `tests/TestLanUpdatePackage.py`, `tests/TestLanUpdateService.py`, `tests/TestLanUpdateApply.py`, `tests/TestLanUpdatePublisher.py`, `tests/TestLanUpdateUI.py`: isolated tests.
- `docs/references/lan-nas-update-runbook.md`: NAS setup, certificate rotation, publish and recovery runbook.
- `docs/references/personal-release-pipeline.md`, `docs/程序结构说明.md`, `更新日志.md`, `config.py`: release and architecture integration.

### Task 1: Strict release manifest

**Files:**
- Create: `src/update/__init__.py`
- Create: `src/update/lan_manifest.py`
- Create: `tests/TestLanUpdateManifest.py`

**Interfaces:**
- Produces: `LanRelease.from_bytes(data: bytes, *, expected_channel: str = "stable") -> LanRelease`
- Produces: `parse_version(value: str) -> tuple[int, int, int]`
- `LanRelease` fields: `schema_version: int`, `channel: str`, `version: str`, `package: str`, `sha256: str`, `size: int`, `published_at: datetime`
- Produces: `LanManifestError(ValueError)`

- [ ] **Step 1: Write table-driven failing tests**

Test one valid document plus invalid UTF-8/JSON, missing and extra keys, boolean integers, non-fixed-width versions, non-stable channel, uppercase/bad hash, zero/oversized size, non-UTC time, package/version mismatch, absolute/backslash/query/percent/empty-dot-dot path, current version equality and downgrade. Assert `LanManifestError` rather than incidental exceptions.

```python
def test_release_rejects_traversal(self):
    raw = valid_manifest(package="releases/v1.40.03/../evil.zip")
    with self.assertRaises(LanManifestError):
        LanRelease.from_bytes(raw)

def test_version_order_is_numeric(self):
    self.assertGreater(parse_version("1.40.03"), parse_version("1.39.12"))
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `\.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestLanUpdateManifest.py`

Expected: FAIL because `src.update.lan_manifest` does not exist.

- [ ] **Step 3: Implement the immutable parser**

Use a frozen dataclass, `json.loads`, exact `set(record) == REQUIRED_KEYS`, `type(value) is int`, `PurePosixPath`, regex full matches, and `datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)`. Add:

```python
def is_newer_than(self, current: str) -> bool:
    return parse_version(self.version) > parse_version(current)

def package_url(self, manifest_url: str) -> str:
    base = manifest_url.rsplit('/', 1)[0] + '/'
    return urllib.parse.urljoin(base, self.package)
```

Require the joined URL to retain the manifest scheme and authority.

- [ ] **Step 4: Run the focused test and confirm GREEN**

Run the Step 2 command. Expected: all cases PASS.

- [ ] **Step 5: Commit the parser**

```powershell
git add src/update/__init__.py src/update/lan_manifest.py tests/TestLanUpdateManifest.py
git commit -m "feat: validate LAN update manifests"
```

### Task 2: Authenticated bounded HTTPS transport

**Files:**
- Create: `src/update/lan_transport.py`
- Create: `tests/TestLanUpdateTransport.py`

**Interfaces:**
- Consumes: manifest URL and expected package metadata.
- Produces: `HttpsPinnedClient(certificate_sha256: str, ca_file: Path | None, connect_timeout: float = 5.0)`
- Produces: `get_bytes(url: str, *, max_bytes: int, deadline_seconds: float) -> bytes`
- Produces: `download(url: str, destination: Path, *, expected_size: int, expected_sha256: str, deadline_seconds: float = 120.0) -> Path`
- Produces: `LanTransportError(RuntimeError)` and `CertificatePinError(LanTransportError)`.

- [ ] **Step 1: Write local TLS-server tests**

Check correct CA+pin, incorrect pin, untrusted CA, HTTP URL, redirect, non-200 response, oversized `Content-Length`, chunked oversize, truncation, timeout, hash mismatch and success. Assert failed downloads leave neither destination nor `destination.with_suffix(destination.suffix + '.part')`.

```python
def test_wrong_pin_never_returns_body(self):
    client = HttpsPinnedClient("0" * 64, self.ca_file)
    with self.assertRaises(CertificatePinError):
        client.get_bytes(self.url, max_bytes=65536, deadline_seconds=2)
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `\.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestLanUpdateTransport.py`

Expected: FAIL because the transport module does not exist.

- [ ] **Step 3: Implement one-request HTTPS transport**

Parse with `urllib.parse.urlsplit`; require scheme `https`, no credentials or fragment, and an explicit hostname. Build `ssl.create_default_context(cafile=...)`, open `http.client.HTTPSConnection`, call `connect()`, hash `connection.sock.getpeercert(binary_form=True)`, compare with `hmac.compare_digest`, then issue a path/query GET. Reject all 3xx responses rather than following redirects. Stream 64 KiB chunks while enforcing monotonic deadline, advertised length and actual length; download into a sibling `.part`, `flush`, `os.fsync`, verify digest, then `os.replace`.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run the Step 2 command. Expected: all transport tests PASS with no external network.

- [ ] **Step 5: Commit the transport**

```powershell
git add src/update/lan_transport.py tests/TestLanUpdateTransport.py
git commit -m "feat: add pinned HTTPS update transport"
```

### Task 3: Reusable package validation

**Files:**
- Create: `src/update/package_validation.py`
- Modify: `scripts/verify_update_package.py`
- Create: `tests/TestLanUpdatePackage.py`

**Interfaces:**
- Produces: `ValidatedPackage(version: str, framework: str, files: Mapping[str, str])`
- Produces: `validate_package(archive: Path, *, expected_version: str, expected_sha256: str, expected_size: int) -> ValidatedPackage`
- Produces: `UpdatePackageError(ValueError)`.
- `scripts.verify_update_package.verify_update()` consumes the shared validator and retains its current return shape.

- [ ] **Step 1: Write malicious and valid ZIP tests**

Cover duplicate case-folded names, absolute/traversal/backslash paths, symlink metadata, unknown/missing member, outer size/hash mismatch, invalid embedded JSON, outer/inner version mismatch, per-file mismatch and a real package from `打包更新.build_package()`.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `\.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestLanUpdatePackage.py`

Expected: FAIL because `validate_package` does not exist.

- [ ] **Step 3: Extract validation without extracting files**

Reuse `scripts.package_smoke.inspect_member`, require exact equality between ZIP members and `manifest['files'] + {'update-manifest.json'}`, reject link mode bits from `ZipInfo.external_attr`, and hash archive members while reading. Return a frozen dataclass with `MappingProxyType(dict(files))`. Refactor the offline verifier to call this function before its temporary-checkout comparison.

- [ ] **Step 4: Run package tests and existing regression**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestLanUpdatePackage.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestPackageSmoke.py
```

Expected: both PASS.

- [ ] **Step 5: Commit package validation**

```powershell
git add src/update/package_validation.py scripts/verify_update_package.py tests/TestLanUpdatePackage.py
git commit -m "refactor: share update package validation"
```

### Task 4: Atomic NAS publisher

**Files:**
- Create: `scripts/publish_lan_update.py`
- Create: `tests/TestLanUpdatePublisher.py`

**Interfaces:**
- Consumes: `verify_update(archive, root, previous_ref)` and `LanRelease` schema.
- Produces: `publish(archive: Path, destination: Path, *, channel: str, previous_ref: str, published_at: datetime) -> Path` returning final `latest.json`.
- CLI requires `archive`, `--destination`, and `--previous-ref`; optional `--channel stable`.

- [ ] **Step 1: Write filesystem and fault-injection tests**

Use temporary directories to verify immutable version layout, exact `SHA256SUMS.txt`, deterministic JSON, identical idempotent publish, conflicting-version refusal, `latest.json` written last, and cleanup of temporary files after injected copy/hash/replace failure.

```python
with patch("scripts.publish_lan_update._replace", side_effect=OSError("disk full")):
    with self.assertRaises(PublishError):
        publish(...)
self.assertEqual(old_latest, latest.read_bytes())
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `\.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestLanUpdatePublisher.py`

Expected: FAIL because the publisher does not exist.

- [ ] **Step 3: Implement same-directory temporary publication**

Copy to `name.tmp-<uuid>`, flush and `os.fsync`, reread and hash, then `os.replace`. Refuse any destination whose resolved version directory escapes `<destination>/<channel>/releases`. Construct `latest.json` from the final archive stat and digest, and replace it only after both immutable files exist. Do not accept credentials or a remote URL.

- [ ] **Step 4: Run focused tests and a dry publication**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestLanUpdatePublisher.py
.\.venv\Scripts\python.exe .\打包更新.py .\dist\lan-test
.\.venv\Scripts\python.exe .\scripts\publish_lan_update.py .\dist\lan-test\okww_update_v1.40.02.zip --destination $env:TEMP\okww-lan-publish --previous-ref v1.40.01
```

Expected: tests PASS; dry destination contains `stable/latest.json` and `stable/releases/v1.40.02/` with no `.tmp-*` files. Remove only the explicit `%TEMP%\okww-lan-publish` dry-run directory after verifying its resolved path is under `%TEMP%`.

- [ ] **Step 5: Commit the publisher**

```powershell
git add scripts/publish_lan_update.py tests/TestLanUpdatePublisher.py
git commit -m "feat: publish updates atomically to NAS"
```

### Task 5: Client check, download and immutable apply request

**Files:**
- Create: `src/update/lan_service.py`
- Create: `tests/TestLanUpdateService.py`

**Interfaces:**
- Produces: `LanUpdateConfig.load(path: Path) -> LanUpdateConfig`
- Produces: `UpdateAvailability(status: Literal['disabled','up_to_date','available'], release: LanRelease | None, message: str)`
- Produces: `LanUpdateService.check(current_version: str) -> UpdateAvailability`
- Produces: `LanUpdateService.download(release: LanRelease, install_root: Path) -> Path`
- Produces: `LanUpdateService.create_apply_request(release: LanRelease, archive: Path, install_root: Path, restart_command: Sequence[str]) -> Path`

- [ ] **Step 1: Write service tests with fake transport**

Test disabled/missing/bad config, up-to-date, downgrade rejection, successful availability, manifest/package disagreement, staging path confinement, preserved existing verified download, cleanup of partial download, and canonical JSON request containing version, archive absolute path, archive hash/size, install root, parent PID and restart argv.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `\.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestLanUpdateService.py`

Expected: FAIL because the service does not exist.

- [ ] **Step 3: Implement orchestration with no installation writes**

Load `configs/lan_update.json` through strict JSON/type checks. `check()` downloads at most 64 KiB and parses `LanRelease`; `download()` writes only below `configs/update-staging/v{version}` and invokes `validate_package`; `create_apply_request()` uses `request.json.tmp` plus `os.replace`, rejects a root containing unresolved links, and never invokes the helper itself.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run the Step 2 command. Expected: all service tests PASS.

- [ ] **Step 5: Commit service orchestration**

```powershell
git add src/update/lan_service.py tests/TestLanUpdateService.py
git commit -m "feat: stage verified LAN product updates"
```

### Task 6: Post-exit transactional apply and rollback

**Files:**
- Create: `src/update/lan_apply.py`
- Create: `tests/TestLanUpdateApply.py`

**Interfaces:**
- Produces: `apply_request(request_path: Path, *, wait_timeout: float = 30.0, fault_hook: Callable[[str, Path], None] | None = None) -> ApplyResult`
- Produces: CLI `python lan_apply.py REQUEST_PATH` with exit codes `0` success, `2` rejected request, `3` rolled back, `4` rollback incomplete.
- Result file: `configs/update-result.json` with `schema_version`, `from_version`, `to_version`, `status`, `message`, `finished_at`, and `backup_dir`.

- [ ] **Step 1: Write synthetic-install tests**

Create a fake old root and package. Test parent timeout, request/archive tampering, changed requirements/framework, config preservation, stale Python removal, successful replacement, restart argv preservation, and a fault after every `os.replace`/delete boundary. For each injected fault assert old controlled-file hashes and config marker are restored.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `\.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestLanUpdateApply.py`

Expected: FAIL because the apply helper does not exist.

- [ ] **Step 3: Implement journaled application**

Validate before mutation. Extract only validated regular members to `<root>/configs/update-staging/.../extracted`. Copy every affected old file to `<root>/configs/update-backups/vOLD-to-vNEW`; write and fsync `journal.json` before replacement. After each successful `os.replace`, append and fsync the operation. On error, replay the journal backward: restore old files and remove newly introduced files. Use `Path.resolve()` plus `is_relative_to(root)` on every source/target and never recursively delete a computed path. Write the result atomically and invoke the exact validated restart argv only after success or completed rollback.

- [ ] **Step 4: Run focused tests and package verifier**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestLanUpdateApply.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestPackageSmoke.py
```

Expected: PASS; failure-injection cases report rollback with the original tree intact.

- [ ] **Step 5: Commit the apply helper**

```powershell
git add src/update/lan_apply.py tests/TestLanUpdateApply.py
git commit -m "feat: apply LAN updates with rollback"
```

### Task 7: Settings UI and safe process handoff

**Files:**
- Create: `src/gui/LanUpdateCard.py`
- Modify: `custom_ok/ok/gui/settings/SettingTab.py`
- Modify: `custom_ok/ok/gui/MainWindow.py`
- Create: `tests/TestLanUpdateUI.py`
- Modify: `tests/TestMainWindowStartup.py`

**Interfaces:**
- `LanUpdateCard(config_path: Path, current_version: str, executor, parent=None)` emits `apply_requested(Path)` only after explicit confirmation.
- `MainWindow.schedule_lan_update(request_path: Path) -> None` copies `src/update/lan_apply.py` to `%TEMP%/okww-update-<uuid>/lan_apply.py`, launches it with the current interpreter and request path, then calls `self.app.quit()`.

- [ ] **Step 1: Write UI/controller tests**

Mock service and dialogs. Assert disabled configuration explains how to enable it; checking is background-only; errors are sanitized; available version requires confirmation; running tasks disable install; cancel performs no launch; helper launch uses `CREATE_NO_WINDOW`, an absolute temporary script and request path; app quits only after `Popen` succeeds; startup reads and displays success/rollback result once.

- [ ] **Step 2: Run focused tests and confirm RED**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestLanUpdateUI.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestMainWindowStartup.py
```

Expected: new UI tests FAIL before implementation; existing startup tests remain PASS.

- [ ] **Step 3: Add the card and handoff**

Use the existing `BackgroundOperation` pattern. Add a separate `SettingCardGroup('局域网更新')` to normal settings. Never log the full URL path, local staging path content, certificate, response body or request JSON. In `schedule_lan_update`, copy the helper plus its imported update modules into the temporary directory, launch `[sys.executable, helper, request]`, and quit only after successful process creation. Keep `pyappify.upgrade(...)` unchanged.

- [ ] **Step 4: Run focused tests and UI group regression**

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestLanUpdateUI.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestMainWindowStartup.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestFiveSectionMainWindow.py
```

Expected: all PASS.

- [ ] **Step 5: Commit UI integration**

```powershell
git add src/gui/LanUpdateCard.py custom_ok/ok/gui/settings/SettingTab.py custom_ok/ok/gui/MainWindow.py tests/TestLanUpdateUI.py tests/TestMainWindowStartup.py
git commit -m "feat: add LAN update controls"
```

### Task 8: Deployment and maintenance documentation

**Files:**
- Create: `docs/references/lan-nas-update-runbook.md`
- Modify: `docs/references/personal-release-pipeline.md`
- Modify: `docs/程序结构说明.md`

- [ ] **Step 1: Write the NAS runbook**

Include exact sections for: NAS HTTPS virtual directory, read-only client/write-only publisher permissions, DNS/hostname, certificate export and SHA-256 calculation, sample `configs/lan_update.json`, dry publication, production publication, client acceptance matrix, certificate rotation order, failed-update recovery, backup retention, and explicit statement that the switch is transport only.

- [ ] **Step 2: Update release-pipeline documentation**

Document two independent outputs: GitHub complete installer and LAN source update. Add the command:

```powershell
.\.venv\Scripts\python.exe .\打包更新.py .\dist\lan
.\.venv\Scripts\python.exe .\scripts\verify_update_package.py .\dist\lan\okww_update_v1.41.00.zip --previous-ref v1.40.02
.\.venv\Scripts\python.exe .\scripts\publish_lan_update.py .\dist\lan\okww_update_v1.41.00.zip --destination "\\NAS\OKWW-Updates" --previous-ref v1.40.02
```

State that these commands are the concrete `1.40.02` to `1.41.00` release example, future releases must substitute both exact tags, and `latest.json` must never be copied manually before its package.

- [ ] **Step 3: Update the program structure reference**

Add the publisher → manifest → pinned HTTPS → staging → external apply → rollback flow; identify `update_pyappify` and `upstream_check.py` as unrelated mechanisms.

- [ ] **Step 4: Review documentation commands**

Run: `rg -n "http://|update_pyappify|latest.json|publish_lan_update" docs/references/lan-nas-update-runbook.md docs/references/personal-release-pipeline.md docs/程序结构说明.md`

Expected: no client `http://` instruction; all three update mechanisms are distinguished; publication order is stated.

- [ ] **Step 5: Commit documentation**

```powershell
git add docs/references/lan-nas-update-runbook.md docs/references/personal-release-pipeline.md docs/程序结构说明.md
git commit -m "docs: document LAN NAS update operations"
```

### Task 9: Version, release notes and complete verification

**Files:**
- Modify: `config.py`
- Modify: `更新日志.md`
- Test: all files from Tasks 1–7 plus release validation.

- [ ] **Step 1: Select and synchronize the release version**

Treat the feature as a medium change: increment `1.40.02` to `1.41.00`. Set `config.py` to `version = "1.41.00"` and add a matching `1.41.00` section to `更新日志.md` describing NAS publishing, authenticated LAN download, explicit confirmation, rollback, and the source-only dependency restriction.

- [ ] **Step 2: Run focused LAN update tests**

```powershell
$tests = @('TestLanUpdateManifest.py','TestLanUpdateTransport.py','TestLanUpdatePackage.py','TestLanUpdatePublisher.py','TestLanUpdateService.py','TestLanUpdateApply.py','TestLanUpdateUI.py')
foreach ($test in $tests) { .\.venv\Scripts\python.exe .\scripts\run_test_file.py (Join-Path .\tests $test); if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }
```

Expected: every file PASS with zero failed tests.

- [ ] **Step 3: Run repository regression and release validation**

```powershell
.\run_tests.ps1 -Group unit
.\run_tests.ps1 -Group integration
.\run_tests.ps1 -Group ui
.\.venv\Scripts\python.exe .\scripts\validate_release.py --tag v1.41.00
```

Expected: all configured tests PASS and release validation exits 0.

- [ ] **Step 4: Build and verify the actual update archive**

```powershell
.\.venv\Scripts\python.exe .\打包更新.py .\dist\lan
.\.venv\Scripts\python.exe .\scripts\verify_update_package.py .\dist\lan\okww_update_v1.41.00.zip --previous-ref v1.40.02
```

Expected: verifier reports version `1.41.00`, matching file hashes, and `configs_preserved: true`.

- [ ] **Step 5: Commit release metadata**

```powershell
git add config.py 更新日志.md
git commit -m "chore: release v1.41.00"
```

### Task 10: Controlled real-LAN acceptance and publication

**Files:**
- Create during execution: `docs/reviews/2026-09-08-LAN-NAS更新验收.md`

- [ ] **Step 1: Publish to a non-production NAS acceptance channel**

Run the publisher against an explicitly resolved acceptance directory such as `\\NAS\OKWW-Updates-Acceptance`; record the command without credentials, archive SHA-256, manifest URL, NAS certificate SHA-256, start time and final directory listing.

- [ ] **Step 2: Execute the four-case client matrix**

On one non-primary client, record: internet disconnected/LAN connected success; network interruption during download leaves version unchanged; wrong certificate fingerprint is rejected; injected apply failure rolls back and the old version starts. Confirm account configs and a synthetic marker remain byte-identical.

- [ ] **Step 3: Record limitations and evidence**

Write actual versions, machine roles, pass/fail results, relevant sanitized log excerpts and backup/result paths into the review file. Do not claim NAS models, certificate rotation or rollback scenarios that were not exercised.

- [ ] **Step 4: Publish stable only after acceptance passes**

Use the exact production UNC directory supplied by the operator. Read back `stable/latest.json` over the client HTTPS URL, verify the pinned certificate and archive hash with the client service, and confirm it reports `1.41.00` available before installing on other clients.

- [ ] **Step 5: Commit evidence, tag and push**

Stage only intended files; explicitly exclude unrelated existing deletions under `docs/reviews/`.

```powershell
git status --short
git add docs/reviews/2026-09-08-LAN-NAS更新验收.md
git commit -m "docs: record LAN NAS update acceptance"
git tag -a v1.41.00 -m "v1.41.00"
git push origin HEAD
git push origin v1.41.00
```

Expected: branch and annotated tag are visible on the publishing remote; the NAS stable manifest and Git tag both identify `1.41.00`.
