import unittest
from pathlib import Path
import tempfile

import numpy as np

from src.android import (
    AdbResult,
    AdbRunner,
    AgentArtifactInspector,
    DevicePreflightService,
    PackageDetector,
    NemuIpcError,
    NemuIpcFrameProvider,
    PreflightError,
    PreflightReport,
)


class FakeAdb:
    def __init__(self, *, package_output="package:com.kurogame.mingchao\n"):
        self.package_output = package_output
        self.commands = []

    def command(self, serial, *args, **kwargs):
        self.commands.append((serial, args))
        if args == ("get-state",):
            return AdbResult((), 0, "device\n", "")
        raise AssertionError(f"unexpected command: {args}")

    def shell(self, serial, args, **kwargs):
        self.commands.append((serial, ("shell", *args)))
        args = tuple(args)
        values = {
            ("getprop", "ro.build.version.sdk"): "35\n",
            ("getprop", "ro.product.cpu.abi"): "x86_64\n",
            ("wm", "size"): "Physical size: 1280x720\nOverride size: 1280x720\n",
            ("wm", "density"): "Physical density: 240\nOverride density: 240\n",
            ("dumpsys", "display"): "mDisplayId=0 orientation=landscape\n",
            ("pm", "list", "packages"): self.package_output,
            ("dumpsys", "window"): "mCurrentFocus=Window{abc com.kurogame.mingchao/com.example.Main}\n",
        }
        if args not in values:
            raise AssertionError(f"unexpected shell command: {args}")
        return AdbResult((), 0, values[args], "")


def channel(**overrides):
    value = {
        "emulator": "MuMuPlayer-6.5.5-0",
        "instance_index": 0,
        "adb_serial": "127.0.0.1:7555",
        "serial_unique": True,
    }
    value.update(overrides)
    return value


class TestAndroidPreflight(unittest.TestCase):
    def test_nemu_provider_rejects_unsafe_instance_name(self):
        provider = NemuIpcFrameProvider(r"C:\MuMu", instance_name="..\\escape", instance_index=0)
        with self.assertRaises(NemuIpcError):
            provider()

    def test_minimal_report_is_not_ready(self):
        self.assertFalse(PreflightReport.minimal("127.0.0.1:7555").ready)

    def test_package_detector_returns_only_game_candidates(self):
        detector = PackageDetector()
        self.assertEqual(
            detector.candidates("package:com.kurogame.mingchao\npackage:com.android.settings\n"),
            ("com.kurogame.mingchao",),
        )

    def test_multiple_candidates_fail_closed(self):
        with self.assertRaises(PreflightError):
            PackageDetector().require_unique(("com.kurogame.mingchao", "com.kurogame.mingchao.global"))

    def test_successful_read_only_preflight(self):
        adb = FakeAdb()
        service = DevicePreflightService(
            adb=adb,
            emulator_version="6.5.5",
            frame_capture=lambda _: np.zeros((720, 1280, 3), dtype=np.uint8),
            agent_probe=lambda _: {"jar_present": True, "hash_valid": True, "heartbeat": True},
        )
        report = service.collect(channel())
        self.assertTrue(report.ready)
        self.assertEqual(report.game_package, "com.kurogame.mingchao")
        self.assertEqual(report.screenshot_size, (1280, 720))
        self.assertEqual(report.adb_state, "device")
        self.assertTrue(all(args[0] != "semantic_action" for _, args in adb.commands))

    def test_wrong_resolution_fails_closed(self):
        adb = FakeAdb()

        class WrongResolution(FakeAdb):
            def shell(self, serial, args, **kwargs):
                result = super().shell(serial, args, **kwargs)
                if tuple(args) == ("wm", "size"):
                    return AdbResult((), 0, "Physical size: 1920x1080\n", "")
                return result

        service = DevicePreflightService(
            adb=WrongResolution(),
            emulator_version="6.5.5",
            frame_capture=lambda _: np.zeros((720, 1280, 3), dtype=np.uint8),
            agent_probe=lambda _: {"jar_present": True, "hash_valid": True, "heartbeat": True},
        )
        report = service.collect(channel())
        self.assertFalse(report.ready)
        self.assertTrue(any("1280x720" in error for error in report.errors))

    def test_missing_agent_and_missing_capture_are_errors(self):
        report = DevicePreflightService(
            adb=FakeAdb(),
            emulator_version="6.5.5",
            agent_probe=lambda _: {"jar_present": False, "hash_valid": False, "heartbeat": False},
        ).collect(channel())
        self.assertFalse(report.ready)
        self.assertTrue(any("Nemu IPC" in error for error in report.errors))
        self.assertTrue(any("Agent" in error for error in report.errors))

    def test_agent_artifact_inspector_hashes_local_jar_without_starting_agent(self):
        with tempfile.TemporaryDirectory() as root:
            jar = Path(root) / "agent.jar"
            jar.write_bytes(b"phase01-agent")
            status = AgentArtifactInspector(jar).inspect()
            self.assertTrue(status.jar_present)
            self.assertTrue(status.hash_valid)
            self.assertEqual(len(status.local_sha256), 64)


if __name__ == "__main__":
    unittest.main()
