import tempfile
import unittest
from pathlib import Path

from main import _set_owned_git_proxy


class TestMainProxyConfig(unittest.TestCase):
    def test_proxy_update_preserves_other_http_keys_and_sections(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config"
            config.write_text(
                "[http]\n\tsslVerify = false\n\tproxy = http://old:1\n"
                "[http \"https://example.invalid\"]\n\textraHeader = X-Test: yes\n"
                "[core]\n\tbare = false\n",
                encoding="utf-8",
            )

            _set_owned_git_proxy(config, "127.0.0.1:7890")
            text = config.read_text(encoding="utf-8")
            self.assertIn("sslVerify = false", text)
            self.assertIn("extraHeader = X-Test: yes", text)
            self.assertIn("proxy = http://127.0.0.1:7890", text)
            self.assertNotIn("proxy = http://old:1", text)


if __name__ == "__main__":
    unittest.main()
