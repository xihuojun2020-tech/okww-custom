# v75 staged GPU startup advisory

Status: frozen candidate, 2026-10-11. No production code, driver settings, HDR
settings or release artifacts were changed by this work. No real GPU, process,
registry, overlay log, game, input or NAS queries were performed by the tests.

## Provenance and package ownership

The pinned raw source was fetched again and compared byte-for-byte to the
parent's downloaded source:

* Commit: `90f4d86991329196cf935a19f64d528a16025a4b`.
* Source: <https://raw.githubusercontent.com/ok-oldking/ok-script/90f4d86991329196cf935a19f64d528a16025a4b/ok/util/gpu_driver_settings.py>.
* Size: 35,850 bytes. SHA256:
  `d3620d9ac1ba8765cb7cd5400d1ddcb51c978297db6ffb584dd9b977c27d3d64`.
* License: <https://raw.githubusercontent.com/ok-oldking/ok-script/90f4d86991329196cf935a19f64d528a16025a4b/LICENSE.txt>.
* License size: 34,523 bytes. SHA256:
  `8486a10c4393cee1c25392769ddd3b2d6c242d6ec7928e1414efff7dfb2f07ef`.
  These bytes equal the repository's existing root `LICENSE.txt`, which the
  native gamepack already packages. A separate exact upstream copy is retained
  under the staged vendor directory. Upstream declares AGPL-3.0; the vendor
  source conservatively records AGPL-3.0-only, without claiming a later-version
  grant. Retain the upstream license terms when merging.

`src/runtime/vendor/gpu_driver_settings.py` has pinned source attribution in its
module header. It and `native_gpu_advisory.py` belong to the AGPL gamepack. The
MIT GameFrame core must not vendor or import these detectors directly.

## Reachable behavior and necessary adaptations

The inspected production consumer is
`ok.gui.StartController.check_gpu_driver_post_processing`, which calls
`get_enabled_gpu_driver_post_processing` after device readiness and warns about
the returned driver effects. The standalone boolean convenience wrapper and
command-line main are not part of that consumer and were removed. Unused NVAPI
profile enumeration/info lookups, their structure, helper and constants were
also removed; the live path only reads Base/Global profiles.

The existing NVAPI/DRS binary, optional ADLX, Windows display-query and NVIDIA
overlay parsing code is reused. Logger import points to native_logging. The
top-level function now returns `enabled` features plus complete `checks`
observations. Missing, failed or inconclusive checks keep `enabled=None`.
NVIDIA no-hit/absent-API results are deliberately inconclusive, since the
upstream return value did not distinguish verified off from unavailable.
No unavailable result is logged as `enabled: False`.

Windows HDR remains context for the existing RTX HDR check, rather than an
additional standalone warning. A failed target-monitor mapping, missing active
display information or display-query exception is unknown. RTX HDR is skipped
as unknown when that prerequisite is unknown. It is reported false only when
the prerequisite was observed false. The existing filter-profile false gates
for Dynamic Vibrance and RTX HDR are retained.

`NativeGpuAdvisory.check(device, emit, translate)`:

1. Runs once for the owning advisory object's worker lifetime, including failed
   or skipped attempts. It does not retry.
2. Skips devices without the actual Windows `desktop-handoff` marker, so replay
   and emulator capabilities cannot imply GPU desktop readiness.
3. Uses the existing device's trusted HWND/PID/process creation time and its
   identity check. Resolves the executable through the existing PID with
   psutil, verifies creation time, and checks target identity again after the
   external exe query. It never constructs another device.
4. Emits one existing `task-log` event, with `advisory='gpu-driver'`, status,
   structured observations and enabled features. Only observed enabled effects
   request a GUI/tray notification. Unknown/skipped results remain visible in
   worker diagnostics. The existing GUI notification route requires no new
   event handler.
5. Reports process/detector failures as unknown and logs the boundary failure,
   without aborting task startup. An event-observer failure is logged and does
   not abort startup either. It never changes service enable preferences.

The new guard branches follow the explicit once-only requirement, the device
capability/identity boundary, the process query boundary, optional detector
availability and the diagnostic observer boundary. No driver setters, HDR
setters, configuration flags, additional compatibility mechanisms, injection
or elevated-access workaround were added. Mature upstream API aliases and
read paths were preserved rather than redesigned.

## Startup wiring for root integration

`GPU_ADVISORY_WIRING.patch` is a proposed integration diff, not applied to
production. `git apply --check` passed against the current production files.

The worker invokes an optional package-owned
`device_ready(device, data_dir, emit)` hook immediately after the existing
device preparation, once before Runtime execution. The AGPL native package
retains one NativeGpuAdvisory instance and supplies its package language
callable. Core code only invokes the generic package hook. Repeated service
attempts therefore do not repeat GPU detection. Copy the staged advisory and
vendor source into the gamepack payload before applying that diff. The current
builder includes `src/**/*.py` and the identical root license; the vendor
license text is additional provenance evidence, not a replacement license.

## Checks

```powershell
.\.venv\Scripts\python.exe test_out/gameframe_acceptance/v75-staging/tests/TestNativeGpuAdvisory.py
```

**11 tests passed.** Fixtures cover enabled-warning translation/one-shot
behavior, explicit off versus unknown, device skip, HWND/PID/creation-time
reuse, replacement during exe lookup, process-query failure, detector failure,
observer failure, missing NVAPI/ADLX/target HDR observations, existing
prerequisite gates, a DRS enabled-setting fixture, target overlay text parsing,
and a temporary headless installation import. WinDLL/CDLL loads are forbidden;
the process factory and all queried GPU/file backends are injected or patched.

The wiring patch was checked for applicability but not executed in production.
No real GPU or actual driver/game support, performance, startup responsiveness
or notification appearance is claimed. NVAPI and ADLX are optional; the
candidate does not install either or fetch a driver.

The inherited detector reads Base/Global DRS configuration, heuristic DRS
database records, recent target-path-correlated NVIDIA overlay logs, and the
first ADLX GPU. Those observations are configuration evidence, not proof that
the selected game rendered a particular effect. Hybrid-GPU applicability,
stale-log correlation, unavailable access and real feature behavior need
separate acceptance. Read calls can block; no bounded detector runtime is
claimed. Checking an HWND/process identity cannot eliminate the check-to-call
race. GPU warnings never control whether combat stays enabled.

## v75 translation messages for root's unified sync

No catalogs were modified for this candidate. Display translation is supplied
by the package; status IDs and diagnostic `checks` fields remain stable.

* `GPU Driver Warning`
* `{vendor} {feature} is enabled and may cause malfunctions!`
* `GPU driver check incomplete; unavailable results remain unknown.`
* `GPU driver checks completed; no enabled effects were detected.`
* `GPU driver check skipped for this device.`
* `GPU driver check failed; state remains unknown ({error}).`
* `Filter Profile`
* `Image Sharpening`
* `RTX Dynamic Vibrance`
* `RTX HDR`
* `Radeon Image Sharpening`

No new global settings or task metadata groups are required.

## Candidate SHA256

| File | SHA256 |
| --- | --- |
| `src/runtime/native_gpu_advisory.py` | `D0A253ADB7DE542133D0FC8FAF2E296E4592E427397D4640BE333F2C01BDACA6` |
| `src/runtime/vendor/gpu_driver_settings.py` | `F3AE493B585D13AB0BC78B05DAFAC34928D34C766A3A31F854E46C1941F045BD` |
| `tests/TestNativeGpuAdvisory.py` | `AFD44C536691BA09EC690BF509072D349DC7874BB622256EE494014536CCEFFD` |
