import json
import unittest
from types import SimpleNamespace

from src.android import MuMuDiscovery, MuMuVersionProbe


class Result:
    returncode = 0
    stderr = ""

    def __init__(self, stdout):
        self.stdout = stdout


class TestMuMuDiscovery(unittest.TestCase):
    def test_version_probe_normalizes_file_version(self):
        self.assertEqual(MuMuVersionProbe.parse_file_version("6.5.5.0"), "6.5.5")
        self.assertEqual(MuMuVersionProbe.require("MuMu Player 6.5.5.0"), "6.5.5")

    def test_version_probe_rejects_other_version(self):
        with self.assertRaises(ValueError):
            MuMuVersionProbe.require("MuMu Player 12.0.0")

    def test_manager_version_probe_reads_json(self):
        discovery = MuMuVersionProbe.from_manager(
            "MuMuManager.exe",
            runner=lambda args, **kwargs: Result('{"version":"6.5.5.0"}'),
        )
        self.assertEqual("6.5.5", discovery)

    def test_manager_info_without_adb_fields_uses_display_only_fallback(self):
        payload = json.dumps({
            "0": {
                "index": "0",
                "android_version": "15.0",
                "name": "鸣潮长期-19910000009",
            },
        })
        candidate = MuMuDiscovery(runner=lambda args, **kwargs: Result(payload)).discover()[0]
        self.assertEqual("127.0.0.1:16384", candidate.adb_serial)
        self.assertTrue(candidate.adb_serial_inferred)
        self.assertIsNone(candidate.error)

    def test_discovery_parses_manager_json_without_selecting(self):
        payload = json.dumps({
            "0": {
                "index": 0,
                "adb_host_ip": "127.0.0.1",
                "adb_port": 7555,
                "name": "MuMuPlayer-6.5.5-0",
                "version": "6.5.5.0",
            },
        })
        discovery = MuMuDiscovery(runner=lambda args, **kwargs: Result(payload))
        candidates = discovery.discover()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].adb_serial, "127.0.0.1:7555")
        self.assertEqual(candidates[0].version, "6.5.5")

    def test_resolve_binding_requires_exact_identity(self):
        payload = json.dumps({
            "0": {"index": 0, "adb_host_ip": "127.0.0.1", "adb_port": 7555,
                   "name": "MuMuPlayer-6.5.5-0", "version": "6.5.5.0"},
        })
        candidates = MuMuDiscovery(runner=lambda args, **kwargs: Result(payload)).discover()
        binding = SimpleNamespace(emulator="MuMuPlayer-6.5.5-0", instance_index=0,
                                  adb_serial="127.0.0.1:7555", game_package=None,
                                  resolution=None, density=None, orientation=None)
        self.assertIsNotNone(MuMuDiscovery.resolve_binding(candidates, binding))
        binding.instance_index = 1
        self.assertIsNone(MuMuDiscovery.resolve_binding(candidates, binding))


if __name__ == "__main__":
    unittest.main()
