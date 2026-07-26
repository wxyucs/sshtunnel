import importlib.util
import contextlib
import io
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "sshtunnel.py"
SPEC = importlib.util.spec_from_file_location("sshtunnel_macos", MODULE_PATH)
assert SPEC and SPEC.loader
sshtunnel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sshtunnel)


class SSHTunnelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state_dir = self.root / "state"
        self.config_path = self.root / "config.json"
        self.fake_ssh = self.root / "fake-ssh"
        self.fake_ssh.write_text(
            "#!/bin/sh\n"
            "case \" $* \" in\n"
            "  *\" -G \"*) printf 'proxyjump test-jump\\n'; exit 0 ;;\n"
            "esac\n"
            "trap 'exit 0' TERM INT\n"
            "while :; do sleep 1; done\n",
            encoding="utf-8",
        )
        self.fake_ssh.chmod(self.fake_ssh.stat().st_mode | stat.S_IXUSR)
        self.old_ssh_bin = os.environ.get("SSHTUNNEL_SSH_BIN")
        os.environ["SSHTUNNEL_SSH_BIN"] = str(self.fake_ssh)

    def tearDown(self):
        try:
            config = sshtunnel.load_config(self.config_path)
        except sshtunnel.ConfigError:
            config = None
        if config:
            for proxy in config["proxies"].values():
                sshtunnel.stop_proxy(config, proxy)
            sshtunnel.stop_web(config)
        if self.old_ssh_bin is None:
            os.environ.pop("SSHTUNNEL_SSH_BIN", None)
        else:
            os.environ["SSHTUNNEL_SSH_BIN"] = self.old_ssh_bin
        self.temporary.cleanup()

    def write_config(self, proxies=None, web_port=None):
        if proxies is None:
            proxies = [
                {
                    "name": "primary",
                    "ssh_host": "example.test",
                    "ssh_user": "tester",
                    "socks_port": 18080,
                }
            ]
        if web_port is None:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                web_port = listener.getsockname()[1]
        self.config_path.write_text(
            json.dumps(
                {
                    "state_dir": str(self.state_dir),
                    "web": {"bind_host": "127.0.0.1", "port": web_port},
                    "proxies": proxies,
                }
            ),
            encoding="utf-8",
        )
        return sshtunnel.load_config(self.config_path)

    def test_config_rejects_duplicate_local_endpoint(self):
        proxies = [
            {
                "name": "one",
                "ssh_host": "one.test",
                "ssh_user": "tester",
                "socks_port": 18080,
            },
            {
                "name": "two",
                "ssh_host": "two.test",
                "ssh_user": "tester",
                "socks_port": 18080,
            },
        ]
        with self.assertRaisesRegex(sshtunnel.ConfigError, "conflicts"):
            self.write_config(proxies=proxies)

    def test_deprecated_enabled_alias_and_conflict(self):
        legacy = [
            {
                "name": "legacy",
                "enabled": False,
                "ssh_host": "legacy.test",
                "ssh_user": "tester",
                "socks_port": 18080,
            }
        ]
        config = self.write_config(proxies=legacy)
        self.assertFalse(config["proxies"]["legacy"]["start_by_default"])

        legacy[0]["start_by_default"] = True
        with self.assertRaisesRegex(sshtunnel.ConfigError, "cannot contain both"):
            self.write_config(proxies=legacy)

    def test_multiple_proxies_are_independent(self):
        config = self.write_config(
            proxies=[
                {
                    "name": "one",
                    "ssh_host": "one.test",
                    "ssh_user": "tester",
                    "socks_port": 18080,
                },
                {
                    "name": "two",
                    "ssh_host": "two.test",
                    "ssh_user": "tester",
                    "socks_port": 18081,
                },
            ]
        )
        first = config["proxies"]["one"]
        second = config["proxies"]["two"]

        self.assertTrue(sshtunnel.start_proxy(config, first)[0])
        self.assertTrue(sshtunnel.start_proxy(config, second)[0])
        self.assertTrue(sshtunnel.proxy_status(config, first)["running"])
        self.assertTrue(sshtunnel.proxy_status(config, second)["running"])

        self.assertTrue(sshtunnel.stop_proxy(config, first)[0])
        self.assertFalse(sshtunnel.proxy_status(config, first)["running"])
        self.assertTrue(sshtunnel.proxy_status(config, second)["running"])

    def test_cli_started_proxy_survives_cli_exit(self):
        config = self.write_config()
        result = subprocess.run(
            [
                sys.executable,
                str(MODULE_PATH),
                "--config",
                str(self.config_path),
                "start",
                "primary",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            sshtunnel.proxy_status(config, config["proxies"]["primary"])["running"]
        )

    def test_web_status_page_and_api(self):
        config = self.write_config()
        proxy = config["proxies"]["primary"]
        self.assertTrue(sshtunnel.start_proxy(config, proxy)[0])
        web_started, message = sshtunnel.start_web(config)
        if not web_started:
            log_path = Path(sshtunnel.web_log_path(config))
            log = log_path.read_text(encoding="utf-8") if log_path.exists() else "(no log)"
            self.fail(f"{message}\n{log}")

        url = sshtunnel.web_status(config)["url"]
        with urllib.request.urlopen(f"{url}api/status", timeout=3) as response:
            payload = json.load(response)
        self.assertEqual(payload["proxies"][0]["name"], "primary")
        self.assertTrue(payload["proxies"][0]["running"])
        self.assertTrue(payload["proxies"][0]["start_by_default"])
        self.assertEqual(payload["proxies"][0]["proxy_jump"], "test-jump")
        self.assertNotIn("enabled", payload["proxies"][0])
        self.assertNotIn("identity_file", payload["proxies"][0])
        self.assertNotIn("token", payload["proxies"][0])

        with urllib.request.urlopen(f"{url}healthz", timeout=3) as response:
            self.assertEqual(response.read(), b"ok\n")

        with urllib.request.urlopen(url, timeout=3) as response:
            page = response.read().decode("utf-8")
        self.assertIn("SSH 代理状态", page)
        self.assertIn("primary", page)
        self.assertIn("ProxyJump", page)
        self.assertIn("test-jump", page)

    def test_proxy_jump_uses_effective_ssh_configuration(self):
        config = self.write_config()
        proxy = config["proxies"]["primary"]
        self.assertEqual(sshtunnel.resolve_proxy_jump(proxy), "test-jump")
        status = sshtunnel.proxy_status(config, proxy)
        self.assertEqual(status["proxy_jump"], "test-jump")

    def test_stop_all_cleans_proxy_removed_from_config(self):
        config = self.write_config()
        old_proxy = config["proxies"]["primary"]
        self.assertTrue(sshtunnel.start_proxy(config, old_proxy)[0])

        replacement = [
            {
                "name": "replacement",
                "ssh_host": "replacement.test",
                "ssh_user": "tester",
                "socks_port": 18081,
            }
        ]
        new_config = self.write_config(proxies=replacement)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sshtunnel.command_stop(new_config, [], False), 0)
        self.assertFalse(sshtunnel.proxy_status(config, old_proxy)["running"])


if __name__ == "__main__":
    unittest.main()
