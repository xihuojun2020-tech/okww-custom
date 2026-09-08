import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from src.update.lan_apply import apply_request


class TestLanUpdateApply(unittest.TestCase):
    def fixture(self, temp):
        root = Path(temp)
        (root / "src").mkdir()
        (root / "configs/update-staging/v1.41.00").mkdir(parents=True)
        (root / "requirements.txt").write_text("ok-script==1.2.3\n", encoding="utf-8")
        (root / "requirements.in").write_text("ok-script==1.2.3\n", encoding="utf-8")
        (root / "src/example.py").write_text("old", encoding="utf-8")
        (root / "src/stale.py").write_text("stale", encoding="utf-8")
        (root / "configs/marker.json").write_text("preserve", encoding="utf-8")
        archive = root / "configs/update-staging/v1.41.00/update.zip"
        files = {"src/example.py": b"new", "requirements.txt": (root / "requirements.txt").read_bytes(),
                 "requirements.in": (root / "requirements.in").read_bytes()}
        manifest = {"version": "1.41.00", "framework": "ok-script==1.2.3",
                    "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
        with zipfile.ZipFile(archive, "w") as package:
            for name, data in files.items(): package.writestr(name, data)
            package.writestr("update-manifest.json", json.dumps(manifest))
        request = archive.parent / "apply-request.json"
        request.write_text(json.dumps({"schema_version": 1, "from_version": "1.40.02",
            "to_version": "1.41.00", "archive": str(archive.resolve()),
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "size": archive.stat().st_size,
            "install_root": str(root.resolve()), "parent_pid": 0,
            "restart_command": ["python", "main.py"]}), encoding="utf-8")
        return root, request

    @patch("src.update.lan_apply.subprocess.Popen")
    def test_applies_and_preserves_configs(self, popen):
        with tempfile.TemporaryDirectory() as temp:
            root, request = self.fixture(temp)
            result = apply_request(request)
            self.assertEqual("succeeded", result.status)
            self.assertEqual("new", (root / "src/example.py").read_text())
            self.assertFalse((root / "src/stale.py").exists())
            self.assertEqual("preserve", (root / "configs/marker.json").read_text())
            popen.assert_called_once()

    @patch("src.update.lan_apply.subprocess.Popen")
    def test_failure_rolls_back(self, popen):
        with tempfile.TemporaryDirectory() as temp:
            root, request = self.fixture(temp)
            calls = 0
            def fail_second(stage, path):
                nonlocal calls
                calls += 1
                if calls == 2: raise OSError("injected")
            result = apply_request(request, fault_hook=fail_second)
            self.assertEqual("rolled_back", result.status)
            self.assertEqual("old", (root / "src/example.py").read_text())
            self.assertEqual("stale", (root / "src/stale.py").read_text())


if __name__ == "__main__":
    unittest.main()
