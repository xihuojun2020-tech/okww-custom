import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from src.update.package_validation import UpdatePackageError, validate_package


class TestLanUpdatePackage(unittest.TestCase):
    def make_package(self, root, *, digest=None, duplicate=False):
        archive = Path(root) / "update.zip"
        content = b"print('ok')\n"
        manifest = {"version": "1.40.03", "framework": "ok-script==1.2.3",
                    "files": {"src/example.py": digest or hashlib.sha256(content).hexdigest()}}
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("src/example.py", content)
            if duplicate:
                package.writestr("SRC/EXAMPLE.PY", content)
            package.writestr("update-manifest.json", json.dumps(manifest))
        return archive

    def validate(self, archive):
        return validate_package(archive, expected_version="1.40.03",
                                expected_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                                expected_size=archive.stat().st_size)

    def test_accepts_valid_package(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.validate(self.make_package(temp))
            self.assertEqual("ok-script==1.2.3", result.framework)

    def test_rejects_inner_hash_and_outer_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = self.make_package(temp, digest="0" * 64)
            with self.assertRaises(UpdatePackageError):
                self.validate(archive)
            with self.assertRaises(UpdatePackageError):
                validate_package(archive, expected_version="1.40.03", expected_sha256="0" * 64,
                                 expected_size=archive.stat().st_size)

    def test_rejects_casefold_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(UpdatePackageError):
                self.validate(self.make_package(temp, duplicate=True))


if __name__ == "__main__":
    unittest.main()
