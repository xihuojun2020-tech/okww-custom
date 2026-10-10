# v1.97.75 GPU startup wiring independent review

Scope: `gameframe.worker.main` prepares the selected device before its optional `device_ready` hook; the actual Wuthering Waves package hook owns one `NativeGpuAdvisory`; advisory failures remain visible as unknown results. No production code was changed by this review.

No evidenced root-cause defect was found in this wiring. The device is already prepared when the real package hook runs. One package retains one advisory instance, which marks itself checked before external process/detector/event operations. Repeated hook callers do not repeat these operations. Devices without `desktop-handoff` skip before any process/detector lookup. Process identity and creation-time checks bracket the executable lookup. Detector/query failures emit unknown plus a logged error, and observer errors are logged without propagating into worker startup.

`tests/TestNativeGpuStartup.py` exercises the actual `worker.main`, actual `PackageManifest.load` package entrypoint, actual `plugin.device_ready` and actual advisory with fake devices/process/detector/leases/store/runtime. Its single focused test runs warning, Replay, detector failure, process failure, observer failure and runtime failure cases, plus a package without the optional hook. **Passed in 0.228s** using repository `.venv\Scripts\python.exe -I -X utf8` with explicit repository import path.

Evidence assertions cover:

- device prepare → package hook → run store → runtime order;
- a single detector query and single advisory event even after two additional real package-hook calls;
- Replay status skipped with zero process and detector calls;
- query/detector exceptions recorded as unknown with failure type and logger.error while runtime still runs;
- observer failure logged while startup continues;
- service enable writes contain only True; a caller-owned fake service `_enabled` sentinel remains True;
- normal and runtime-error closing order remains device → package → store → device lease → data lease → package lease;
- old packages lacking the optional hook still launch without advisory construction.

Source review also confirms that the advisory and package hook neither receive a task object nor modify `_enabled` or the enabled store. This focused fixture does not establish real persistent combat recovery behavior; that remains covered by the existing combat tests.

The helper accepts explicit `source_root`, `core_root` and `package_root`, and asserts worker import under the supplied core, advisory under payload/source, and plugin exactly under the supplied package. Repository execution is reported as repository execution. Installed payload/core acceptance requires running the same fixture through the release wrapper with installed roots; this report does not claim that it has happened.

No real DLL/GPU/process query, diagnostic file log, NAS, input, clipboard or game call occurred. DLL/process calls are forbidden guards, GPU detector is injected, advisory logger and language lookup are mocked, and lease/store/runtime are synthetic. Manifest/plugin reads and temporary test scripts are local fixture setup. The worker cleanup finally block was also compared with v74 commit `58879ae35e6d3a827d018e353dfad48e9315a73e`; its ordering is unchanged.
