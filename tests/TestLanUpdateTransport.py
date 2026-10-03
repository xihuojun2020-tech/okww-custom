import hashlib
import tempfile
import unittest
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from src.update.lan_transport import CertificatePinError, FileShareClient, HttpsPinnedClient, LanTransportError
from src.update.lan_transport import _smb_call
from src.update.worker_process import worker_command


class Response:
    status = 200
    def __init__(self, data, length=None): self.data, self.length = data, length
    def getheader(self, name): return str(self.length) if self.length is not None else None
    def read(self, count):
        result, self.data = self.data[:count], self.data[count:]
        return result


class Connection:
    def __init__(self, certificate, response):
        self.sock, self.response = self, response
    def connect(self): pass
    def getpeercert(self, binary_form=False): return b"certificate"
    def request(self, *args, **kwargs): pass
    def getresponse(self): return self.response
    def close(self): pass


class TestLanUpdateTransport(unittest.TestCase):
    def test_worker_inherits_initialized_dependency_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'only_parent_path.py').write_text("VALUE='inherited'")
            sys.path.insert(0, temp)
            try:
                command = worker_command('only_parent_path')
                result = subprocess.run(command, capture_output=True)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn('-E', command)
            finally:
                sys.path.remove(temp)

    @patch('src.update.lan_transport.subprocess.run')
    def test_worker_error_is_not_misreported_as_credentials(self, run):
        run.return_value = subprocess.CompletedProcess([], 2, json.dumps({'error': '更新包长度或 SHA-256 不匹配'}).encode(), b'')
        with self.assertRaisesRegex(LanTransportError, 'SHA-256'):
            _smb_call('download', {}, 2)

    def client(self, data, length=None, pin=None):
        pin = pin or hashlib.sha256(b"certificate").hexdigest()
        client = HttpsPinnedClient(pin)
        client._connection = lambda parsed: Connection(b"certificate", Response(data, length))
        return client

    def test_get_and_atomic_download(self):
        data = b"update bytes"
        client = self.client(data, len(data))
        self.assertEqual(data, client.get_bytes("https://nas.lan/latest.json", max_bytes=100,
                                                deadline_seconds=1))
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "update.zip"
            client = self.client(data, len(data))
            client.download("https://nas.lan/update.zip", target, expected_size=len(data),
                            expected_sha256=hashlib.sha256(data).hexdigest())
            self.assertEqual(data, target.read_bytes())

    def test_rejects_http_and_truncated_body(self):
        with self.assertRaises(LanTransportError):
            self.client(b"x").get_bytes("http://nas/update", max_bytes=10, deadline_seconds=1)
        with self.assertRaises(LanTransportError):
            self.client(b"x", 2).get_bytes("https://nas/update", max_bytes=10, deadline_seconds=1)

    def test_file_share_uses_same_hash_and_atomic_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, target = root / "source.zip", root / "out/update.zip"
            source.write_bytes(b"share")
            client = FileShareClient()
            self.assertEqual(b"share", client.get_bytes(str(source), max_bytes=5, deadline_seconds=1))
            client.download(str(source), target, expected_size=5,
                            expected_sha256=hashlib.sha256(b"share").hexdigest())
            self.assertEqual(b"share", target.read_bytes())

    @patch("src.update.lan_transport.http.client.HTTPSConnection")
    def test_rejects_wrong_certificate_pin(self, connection_type):
        connection_type.return_value = Connection(b"certificate", Response(b"x"))
        client = HttpsPinnedClient("0" * 64)
        with self.assertRaises(CertificatePinError):
            client.get_bytes("https://nas/update", max_bytes=10, deadline_seconds=1)


if __name__ == "__main__":
    unittest.main()
