import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from src.update.lan_service import LanUpdateConfig, LanUpdateError, LanUpdateService
from src.update.lan_manifest import LanRelease


def release_bytes(version="1.41.00", size=1, digest="a" * 64):
    return json.dumps({"schema_version": 1, "channel": "stable", "version": version,
                       "package": f"releases/v{version}/okww_update_v{version}.zip",
                       "sha256": digest, "size": size,
                       "published_at": "2026-09-08T10:00:00Z"}).encode()


class FakeTransport:
    def __init__(self, data): self.data = data
    def get_bytes(self, *args, **kwargs): return self.data
    def download(self, url, destination, **kwargs): Path(destination).write_bytes(self.data); return destination


class TestLanUpdateService(unittest.TestCase):
    def write_config(self, root, **changes):
        value = {"enabled": True, "manifest_url": "https://nas.lan/updates/stable/latest.json",
                 "certificate_sha256": "a" * 64, "ca_file": "", "channel": "stable"}
        value.update(changes)
        path = Path(root) / "lan_update.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_missing_config_uses_personal_nas_share(self):
        with tempfile.TemporaryDirectory() as temp:
            config = LanUpdateConfig.load(Path(temp) / "missing.json")
            self.assertTrue(config.enabled)
            self.assertTrue(config.manifest_url.startswith(r"\\192.168.3.173"))

    def test_reports_newer_and_up_to_date(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.write_config(temp)
            service = LanUpdateService(path, FakeTransport(release_bytes()))
            self.assertEqual("available", service.check("1.40.02").status)
            self.assertEqual("up_to_date", service.check("1.41.00").status)

    def test_enabled_config_requires_https_and_pin(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(LanUpdateError):
                LanUpdateConfig.load(self.write_config(temp, manifest_url="http://nas/update"))

    def test_unc_config_does_not_require_certificate(self):
        with tempfile.TemporaryDirectory() as temp:
            config = LanUpdateConfig.load(self.write_config(
                temp, manifest_url=r"\\nas\share\stable\latest.json", certificate_sha256=""))
            self.assertEqual("", config.certificate_sha256)


if __name__ == "__main__":
    unittest.main()
