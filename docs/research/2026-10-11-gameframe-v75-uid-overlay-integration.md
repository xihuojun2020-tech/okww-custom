# Native UID overlay integration acceptance — v1.97.75

Reviewed scope: AGPL UID ROI processing in `src/runtime/native_uid_overlay.py`; MIT generic patch renderer `gameframe/overlay.py`; native executor/host/plugin boundaries; GameFrame GUI events and lifecycle; legacy Program Preferences migration and metadata. The v74 baseline is commit `58879ae35e6d3a827d018e353dfad48e9315a73e`. Initially reviewed in `test_out/gameframe_acceptance/v75-staging`, then merged into production on the parent task's explicit instruction. WindowsDevice read-only target-provider implementation belongs to the sibling runtime task; GPU readiness/worker/version/i18n belong to the parent.

## Behavior and evidence

- The producer uses the existing UID ROI and works on a local patch. Inpaint processes only ROI plus ten pixels of padding; Blur downsizes to at most 8 × 8, enlarges and blurs. It preserves the original frame. Its monotonic interval is in seconds; it neither captures nor sends input nor starts threads.
- The executor forwards only successful current frames. A capture exception or None-frame timeout clears the overlay. `nullable_frame()` is used during idle scheduling; `_diagnostic_frame` is retained for evidence and never reused for the overlay. Pause/stop and missing/mismatched physical target geometry clear it without modifying the preference.
- Only a context device exposing `overlay_target` constructs a producer. A genuine configuration host with device=None constructs neither producer nor Qt/OCR services.
- Host visual failures are logged and emit `overlay-failed` without failing the successful combat capture. Marking an update active before event emission ensures a post-delivery observer failure can still send its matching clear. Failed clear/report observers are explicitly logged.
- The shared plugin finally clears in session, service and one-shot success/error paths. GUI consumes patch events before ordinary output logging, clearing on pause, finished, worker exit, explicit stop and both close-to-tray and final close. Stopping/closing ignores incoming updates.
- The Qt renderer has transparent/input-pass-through/no-focus flags. A 50ms timer revalidates HWND/PID/process creation-time/foreground/client dimensions and follows physical client movement. SetWindowPos uses physical coordinates and SWP_NOACTIVATE; resized/background/changed-owner targets hide. An old owner's clear cannot hide the current owner. Rendering/placement failures clear and log.
- Exact legacy values for Enable Blur, Blur Algorithm and Blur Interval migrate into Program Preferences. Default is disabled, algorithm Inpaint, interval one second. The schema exposes the two dependent fields beneath Enable Blur, with Blur/Inpaint choices and nonnegative interval.

## Verification

Command used the repository `.venv\Scripts\python.exe -I -X utf8`, explicitly adding the repository to sys.path, and unittest modules `tests.TestNativeUIDOverlay` and `tests.TestOverlayWiring`. Final run: **9 tests passed in 2.162s**.

Focused fixtures cover both processing algorithms/PNG dimensions/original-frame preservation/interval; pause/background/resize/stop; isolated forbidden Qt/legacy imports; injected offscreen geometry with negative coordinates, movement, DPI, changed owner/process/client and placement error; genuine configuration-host migration/device=None; actual executor→host→producer success/capture exception/None timeout/pause/visual failure/post-delivery event error; actual plugin wrapper session/service/one-shot × success/failure common-finally; actual GUI dispatch plus worker exit codes 0/1/-9, stop and close-to-tray/final-close callbacks with mock widgets and thread launch.

The capture call-count assertion confirms no additional producer capture. Enabled blur intent stays true throughout failure tests. Tests do not claim actual Windows placement, DPI behavior, real game visibility, capture backend interoperability, input correctness or on-device battle success. No real Win32 API, game, emulator, input, clipboard, external messaging or NAS access occurred. GUI lifecycle callbacks use synthetic collaborators; physical geometry tests inject a fake adapter.

## Required release integration

The parent must pair this integration with the sibling's WindowsDevice.overlay_target implementation and preserve the tested interface: selected HWND/PID/creation-time, exact foreground ownership, physical client rectangle and actual DPI, read-only/no capture/input/Qt. The parent owns v1.97.75 version synchronization, translations, overall verification and publishing. This report itself makes no claim that those independent release steps are complete.
