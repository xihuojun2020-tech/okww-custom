import tempfile
import unittest
from pathlib import Path

from auto_proxy import (
    find_bootstrap_log,
    find_packaged_app_json,
    find_packaged_git_config,
    find_working_proxy,
    parse_proxy_server,
    restore_auto_update,
    set_git_proxy,
)
from main import _set_owned_git_proxy


class TestMainProxyConfig(unittest.TestCase):
    def test_proxy_update_preserves_other_http_keys_and_sections(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config"
            config.write_text(
                "[http]\n\tsslVerify = false\n\tproxy = http://old:1\n"
                "[https]\n\tproxy = http://legacy:2\n"
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
            self.assertNotIn("proxy = http://legacy:2", text)

    def test_proxy_removal_preserves_other_http_keys_and_sections(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config"
            config.write_text(
                "[http]\n\tsslVerify = false\n\tproxy = http://old:1\n"
                "[https]\n\tproxy = http://legacy:2\n"
                "[http \"https://example.invalid\"]\n\textraHeader = X-Test: yes\n",
                encoding="utf-8",
            )

            set_git_proxy(config, None)
            text = config.read_text(encoding="utf-8")
            self.assertIn("sslVerify = false", text)
            self.assertIn("extraHeader = X-Test: yes", text)
            self.assertNotIn("proxy =", text)

    def test_composite_system_proxy_prefers_https_endpoint(self):
        self.assertEqual(
            parse_proxy_server(
                "http=127.0.0.1:7890;https=127.0.0.1:7897;socks=127.0.0.1:1080"
            ),
            ["127.0.0.1:7897", "127.0.0.1:7890"],
        )

    def test_detector_skips_open_but_unusable_proxy(self):
        attempts = []

        def probe(proxy, _timeout):
            attempts.append(proxy)
            return proxy == "127.0.0.1:7897"

        selected = find_working_proxy(
            system_proxy="127.0.0.1:7890",
            common_ports=(7890, 7897),
            probe=probe,
            timeout=0.01,
        )

        self.assertEqual(selected, "127.0.0.1:7897")
        self.assertEqual(attempts, ["127.0.0.1:7890", "127.0.0.1:7897"])

    def test_working_copy_resolves_outer_package_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            app = root / "data/apps/okww-custom"
            working = app / "working"
            config = app / "repo/.git/config"
            working.mkdir(parents=True)
            config.parent.mkdir(parents=True)
            config.write_text("[core]\n\tbare = false\n", encoding="utf-8")
            app_json = app / "app.json"
            app_json.write_text('{"update_method": "MANUAL_UPDATE"}', encoding="utf-8")

            self.assertEqual(find_packaged_git_config(working), config)
            self.assertEqual(find_packaged_app_json(working), app_json)
            self.assertEqual(find_bootstrap_log(working), root / "logs/proxy_bootstrap.log")
            restore_auto_update(working)
            self.assertIn("AUTO_UPDATE", app_json.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
