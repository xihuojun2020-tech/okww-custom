# Daily Diagnostic Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build date-scoped diagnostic archives, automatically upload overdue days at startup, keep manual uploads limited to today, and display persistent stage, byte progress, speed, elapsed time, and ETA.

**Architecture:** Reuse immutable diagnostic batches as the source of truth and classify them by the local date of `manifest.created_at`. Keep archive construction and transfer in `diagnostic_archive.py`, launch overdue work from `diagnostic_lifecycle.py`, and let Qt poll an atomic progress snapshot.

**Tech Stack:** Python standard library, PySide6, existing `atomic_json`/`FileLease`, unittest/pytest, Windows SMB.

**Spec:** `docs/superpowers/specs/2026-09-16-daily-diagnostic-upload-design.md`

## Global Constraints

- Manual upload includes only today's pending batches; automatic startup upload includes only dates before today, oldest first.
- A ZIP contains one local date only; acknowledged batches never repeat.
- Do not add an archive-size limit or NAS full-file hash rereads.
- Preserve `.partial`, ZIP, receipts, and batches on failure; retain successful local evidence for one day.
- Automatic failure must not block startup or game tasks.
- Use only `\\192.168.3.173\羲火君 共享给我\AI诊断` for real NAS verification.
- Run Python through `.\.venv\Scripts\python.exe` when present.
- Code changes require the fixed-width `config.py` version, changelog, annotated tag, and branch/tag push.

## File Map

- `src/runtime/diagnostic_archive.py`: daily selection, archive building, coordinators, resume, rate/progress.
- `src/runtime/diagnostic_lifecycle.py`: non-blocking startup catch-up.
- `src/gui/DiagnosticStatusCard.py`, `src/gui/DiagnosticDetails.py`: status and today-only copy.
- `tests/TestDiagnosticArchive.py`, `tests/TestDiagnosticStatusCard.py`, `tests/TestMainWindowStartup.py`: behavior and UI regression tests.
- `config.py`, `更新日志.md`: release synchronization.

---

### Task 1: Date-scoped discovery and archive construction

**Files:**
- Modify: `src/runtime/diagnostic_archive.py`
- Test: `tests/TestDiagnosticArchive.py`

**Interfaces:**
- Produces `batch_local_day(manifest: dict) -> str`.
- Produces `pending_days(root: Path, *, today: str | None = None) -> list[str]`.
- Changes `build_archive(root, *, day: str, mode: str, flush_current: bool = False) -> Path`.
- Adds receipt fields `day` and `mode`.

- [ ] **Step 1: Write failing date-selection tests**

```python
def test_pending_days_is_oldest_first_and_excludes_today(self):
    root = self.make_dated_root(("2026-09-14", "2026-09-15", "2026-09-16"))
    self.assertEqual(["2026-09-14", "2026-09-15"],
                     pending_days(root, today="2026-09-16"))

def test_archive_contains_only_requested_day(self):
    root = self.make_dated_root(("2026-09-15", "2026-09-16"))
    archive = build_archive(root, day="2026-09-16", mode="manual")
    receipt = json.loads(archive.with_suffix(".json").read_text(encoding="utf-8"))
    self.assertEqual(("2026-09-16", "manual"), (receipt["day"], receipt["mode"]))
    self.assertEqual({self.run_for("2026-09-16")},
                     {item["key"].split("--", 1)[0] for item in receipt["batches"]})
```

- [ ] **Step 2: Verify failure**

Run `.\.venv\Scripts\python.exe -m pytest tests\TestDiagnosticArchive.py -k "pending_days or requested_day" -q`.
Expected: missing interfaces or old all-pending behavior.

- [ ] **Step 3: Implement local-date selection**

```python
from datetime import date, datetime

def batch_local_day(manifest):
    return datetime.fromtimestamp(float(manifest["created_at"])).date().isoformat()

def pending_days(root, *, today=None):
    cutoff = date.fromisoformat(today) if today else date.today()
    days = set()
    for ready in Path(root).glob("*/batches/*/_READY"):
        batch = ready.parent
        key = batch.parents[1].name + "--" + batch.name
        state_path = Path(root) / "states" / (key + ".json")
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
        day = date.fromisoformat(batch_local_day(manifest))
        if state.get("status") not in ("uploaded", "logs_purged") and day < cutoff:
            days.add(day.isoformat())
    return sorted(days)
```

Require `day`/`mode` in `build_archive`, snapshot only matching pending batches, include the date/mode in filenames, receipt, and internal manifest, and flush the live session only when `flush_current=True`. Referenced incident images may cross dates but must not add their source batch to the receipt acknowledgement list.

- [ ] **Step 4: Run and commit**

Run `.\.venv\Scripts\python.exe -m pytest tests\TestDiagnosticArchive.py tests\TestDiagnosticArchiveRetention.py -q`.
Then commit `src/runtime/diagnostic_archive.py` and `tests/TestDiagnosticArchive.py` as `feat: build daily diagnostic archives`.

---

### Task 2: Stages, resume, speed, and ETA

**Files:**
- Modify: `src/runtime/diagnostic_archive.py`
- Test: `tests/TestDiagnosticArchive.py`

**Interfaces:**
- Produces `write_progress(root: Path, *, mode: str, day: str, stage: str, **fields) -> None`.
- Produces `TransferRate(start_copied: int = 0).update(copied: int, total: int) -> dict`.
- Consumes Task 1 receipt `day` and `mode`.

- [ ] **Step 1: Write failing resume/progress tests**

```python
def test_upload_resumes_partial_and_records_speed(self):
    archive = self.make_archive(payload_size=12 * 1024 * 1024)
    partial = self.partial_for(archive)
    partial.parent.mkdir(parents=True)
    partial.write_bytes(archive.read_bytes()[:4 * 1024 * 1024])
    remote = Path(upload_archive(archive, self.target))
    self.assertEqual(archive.read_bytes(), remote.read_bytes())
    progress = json.loads((archive.parent / "progress.json").read_text(encoding="utf-8"))
    self.assertEqual("uploaded", progress["stage"])
    self.assertGreater(progress["average_speed_bps"], 0)

def test_partial_larger_than_source_restarts(self):
    archive = self.make_archive(payload_size=1024)
    self.partial_for(archive).write_bytes(b"x" * (archive.stat().st_size + 1))
    self.assertEqual(archive.read_bytes(), Path(upload_archive(archive, self.target)).read_bytes())
```

- [ ] **Step 2: Verify failure**

Run `.\.venv\Scripts\python.exe -m pytest tests\TestDiagnosticArchive.py -k "resume or partial or speed" -q`.
Expected: resume or new snapshot fields fail.

- [ ] **Step 3: Implement atomic stages and rolling rate**

Use stages `discovering`, `sealing`, `packing`, `connecting`, `uploading`, `recording`, `uploaded`, `failed`, `idle`. Update at most once per second. Use a five-second `deque` of `(monotonic_time, copied)` samples; calculate average from bytes transferred in this attempt, ETA from current speed, and `None` when speed is zero.

```python
return {"copied": copied, "total": total, "speed_bps": current,
        "average_speed_bps": average, "elapsed_seconds": elapsed,
        "eta_seconds": (total - copied) / current if current > 0 else None}
```

- [ ] **Step 4: Implement resume semantics**

For `0 < partial_size < total`, seek the local source and append to NAS at `partial_size`. For `partial_size > total`, reopen with `wb`; for equality, skip copying. Continue size confirmation and atomic rename without a NAS full-file hash read. On failure, persist `stage="failed"`, `failed_stage`, and sanitized `error`, then re-raise.

- [ ] **Step 5: Run and commit**

Run `.\.venv\Scripts\python.exe -m pytest tests\TestDiagnosticArchive.py tests\TestDiagnosticArchiveRetention.py -q`.
Commit the two task files as `feat: report resumable diagnostic upload progress`.

---

### Task 3: Today-only manual and overdue automatic coordinators

**Files:**
- Modify: `src/runtime/diagnostic_archive.py`
- Modify: `src/runtime/diagnostic_lifecycle.py`
- Test: `tests/TestDiagnosticArchive.py`
- Test: `tests/TestMainWindowStartup.py`

**Interfaces:**
- Produces `manual_upload(root: Path, *, today: str | None = None) -> str`.
- Produces `automatic_upload(root: Path, *, today: str | None = None) -> list[str]`.
- Produces `start_automatic_archive_upload(root: Path) -> threading.Thread`.

- [ ] **Step 1: Write failing coordinator tests**

```python
def test_manual_upload_sends_today_only(self):
    root = self.make_dated_root(("2026-09-15", "2026-09-16"))
    with patch("src.runtime.diagnostic_archive.send_archive", side_effect=self.fake_send):
        manual_upload(root, today="2026-09-16")
    self.assertEqual(["2026-09-16"], self.sent_days)

def test_automatic_upload_sends_overdue_days_oldest_first(self):
    root = self.make_dated_root(("2026-09-13", "2026-09-15", "2026-09-16"))
    with patch("src.runtime.diagnostic_archive.send_archive", side_effect=self.fake_send):
        automatic_upload(root, today="2026-09-16")
    self.assertEqual(["2026-09-13", "2026-09-15"], self.sent_days)
```

Add a startup test proving one daemon worker is started and `start_diagnostics` returns without joining it.

- [ ] **Step 2: Verify failure**

Run `.\.venv\Scripts\python.exe -m pytest tests\TestDiagnosticArchive.py tests\TestMainWindowStartup.py -k "manual_upload or automatic_upload or diagnostic" -q`.

- [ ] **Step 3: Implement coordinators**

Manual upload resolves `today`, writes `sealing`, flushes the live session, builds exactly today, and reports `今天没有待上传的日志或截图` when empty. It ignores legacy cross-date `packed`/`oversized` receipts. Automatic upload snapshots `pending_days`, uploads them oldest first, stops on the first failure, and writes `idle` when none exist.

- [ ] **Step 4: Start automatic work without blocking startup**

```python
def start_automatic_archive_upload(root):
    worker = threading.Thread(target=_automatic_archive_worker, args=(Path(root),),
                              name="DailyDiagnosticUpload", daemon=True)
    worker.start()
    return worker

def _automatic_archive_worker(root):
    try:
        from src.runtime.diagnostic_archive import automatic_upload
        automatic_upload(root)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        logging.getLogger(__name__).warning("daily diagnostic upload failed: %s",
                                            sanitize_text(error))
```

- [ ] **Step 5: Run and commit**

Run `.\.venv\Scripts\python.exe -m pytest tests\TestDiagnosticArchive.py tests\TestMainWindowStartup.py tests\TestDiagnosticPolicy.py -q`.
Commit the four task files as `feat: upload overdue diagnostics at startup`.

---

### Task 4: GUI stage, speed, and ETA display

**Files:**
- Modify: `src/gui/DiagnosticStatusCard.py`
- Modify: `src/gui/DiagnosticDetails.py`
- Test: `tests/TestDiagnosticStatusCard.py`

**Interfaces:**
- Produces `format_archive_progress(progress: dict) -> str`.
- Consumes Task 2 progress schema.

- [ ] **Step 1: Write failing formatter tests**

```python
def test_progress_formats_speed_and_eta(self):
    text = format_archive_progress({"mode": "automatic", "day": "2026-09-15",
        "stage": "uploading", "copied": 650117120, "total": 1621932239,
        "speed_bps": 19451084, "average_speed_bps": 18126322,
        "elapsed_seconds": 35.8, "eta_seconds": 49.9})
    self.assertIn("自动上传：2026-09-15", text)
    self.assertIn("MiB/s", text)
    self.assertIn("预计剩余：50 秒", text)

def test_progress_formats_packing_batches(self):
    text = format_archive_progress({"mode": "manual", "day": "2026-09-16",
        "stage": "packing", "completed_batches": 1250, "total_batches": 1840})
    self.assertIn("批次：1250 / 1840", text)
```

- [ ] **Step 2: Verify failure**

Run `.\.venv\Scripts\python.exe -m pytest tests\TestDiagnosticStatusCard.py -k progress -q`.

- [ ] **Step 3: Implement pure formatting and polling**

Add byte, duration, percentage, mode, and stage formatters. Clamp percent to `0..100`; render missing ETA as `计算中`; sanitize errors through `diagnostic_error_message`. Poll active progress once per second using the existing Qt timer and atomic file reads; never pass widgets into `BackgroundOperation`.

- [ ] **Step 4: Update manual copy**

Use `正在打包并上传今天的日志与截图` and `今日诊断资料已上传` in both UI entry points.

- [ ] **Step 5: Run and commit**

Run `.\.venv\Scripts\python.exe -m pytest tests\TestDiagnosticStatusCard.py tests\TestDiagnosticDetails.py tests\TestDiagnosticDetailsUI.py -q`.
Commit the three task files as `feat: show diagnostic upload speed and stages`.

---

### Task 5: Release synchronization and verification

**Files:**
- Modify: `config.py`
- Modify: `更新日志.md`

**Interfaces:**
- Produces version `1.77.05`, tag `v1.77.05`, and published branch/tag.

- [ ] **Step 1: Synchronize release metadata**

Change `version = "1.77.04"` to `version = "1.77.05"`. Add top release notes covering daily selection, startup catch-up, resume, stages, speed, and ETA.

- [ ] **Step 2: Run focused suites**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\TestDiagnosticArchive.py tests\TestDiagnosticArchiveRetention.py tests\TestDiagnosticStatusCard.py tests\TestDiagnosticDetails.py tests\TestMainWindowStartup.py tests\TestDiagnosticPolicy.py -q
```

- [ ] **Step 3: Run integration and release checks**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_tests.ps1 integration
.\.venv\Scripts\python.exe -m pytest tests\TestPackageSmoke.py tests\TestReleaseReadiness.py tests\TestNasLocation.py -q
git diff --check
```

- [ ] **Step 4: Perform bounded packaged/NAS verification**

Use a small synthetic current-day batch and older-day batch. Confirm UI stages and nonzero speed, manual exclusion of the old batch, startup selection of the old batch, and formal ZIP/receipt creation only under `\\192.168.3.173\羲火君 共享给我\AI诊断\待分析\压缩包`. Do not mark a ZIP reviewed without inspecting it and writing the required substantive report.

- [ ] **Step 5: Commit and publish**

Commit `config.py` and `更新日志.md` as `release: publish daily diagnostic uploads`. Verify `v1.77.05` does not exist, create annotated tag `v1.77.05`, push `HEAD` and the tag to `origin`, then verify both with `git ls-remote`.
