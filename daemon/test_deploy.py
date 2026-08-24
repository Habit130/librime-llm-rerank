#!/usr/bin/env python3
"""Portable daemon deploy path (Habit130/squirrel#131, AC-131-v1)."""

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import deploy

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKOUT = os.path.dirname(HERE)
HABIT_PATH = re.compile(r"/Users/habit")


class PinAndTemplateTest(unittest.TestCase):
    def test_inference_pins_are_exact(self):
        path = os.path.join(HERE, "requirements-daemon.txt")
        pins = {}
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                name, version = line.split("==")
                pins[name] = version
        self.assertEqual({"mlx", "mlx-lm", "numpy"}, set(pins))
        for version in pins.values():
            self.assertRegex(version, r"^\d+\.\d+\.\d+$")

    def test_plist_template_has_no_maintainer_paths(self):
        path = os.path.join(HERE, "com.squirrel.llm-rerank.plist")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIsNone(HABIT_PATH.search(text))
        for token in (
            "__CHECKOUT__",
            "__INTERPRETER__",
            "__SERVER__",
            "__MODEL__",
            "__SOCKET__",
            "__LOG__",
            "__LOG_ERR__",
            "__FACTS_ROOT__",
        ):
            self.assertIn(token, text)

    def test_server_default_model_is_not_a_maintainer_path(self):
        with open(os.path.join(HERE, "server.py"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("/Users/habit/Models", text)

    def test_render_plist_substitutes_explicit_paths(self):
        values = {
            "checkout": "/tmp/checkout",
            "interpreter": "/tmp/checkout/daemon/.venv/bin/python",
            "server": "/tmp/checkout/daemon/server.py",
            "model": "/tmp/models/Qwen3-0.6B-Base",
            "socket": "/tmp/run/llm-rerank.sock",
            "log": "/tmp/run/llm-rerank.log",
            "log_err": "/tmp/run/llm-rerank.err",
            "facts_root": "/tmp/run/facts",
        }
        rendered = deploy.render_plist(
            os.path.join(HERE, "com.squirrel.llm-rerank.plist"), values
        )
        self.assertIsNone(HABIT_PATH.search(rendered))
        self.assertNotRegex(rendered, r"__[A-Z0-9_]+__")
        for value in values.values():
            self.assertIn(value, rendered)


class IsolatedLifecycleTest(unittest.TestCase):
    def _owner_dir(self, path):
        os.mkdir(path, 0o700)
        os.chmod(path, 0o700)

    def test_start_health_stop_health_only(self):
        root = tempfile.mkdtemp(prefix="llm131-life-")
        try:
            runtime = os.path.join(root, "run")
            self._owner_dir(runtime)
            socket_path = os.path.join(runtime, "llm-rerank.sock")
            argv = [
                "--checkout", CHECKOUT,
                "--runtime-dir", runtime,
                "--interpreter", sys.executable,
                "--socket", socket_path,
                "--log", os.path.join(runtime, "llm-rerank.log"),
                "--log-err", os.path.join(runtime, "llm-rerank.err"),
                "--facts-root", os.path.join(runtime, "facts"),
                "--pid-file", os.path.join(runtime, "daemon.pid"),
            ]
            self.assertEqual(
                0, deploy.main(argv + ["start", "--health-only", "--timeout", "10"])
            )
            try:
                self.assertEqual(0, deploy.main(argv + ["health"]))
                response = deploy.send_health(socket_path)
                self.assertEqual("health", response["kind"])
                self.assertFalse(response["health"]["model_loaded"])
                self.assertIsInstance(response["health"]["pid"], int)
                self.assertTrue(os.path.exists(socket_path))
            finally:
                self.assertEqual(0, deploy.main(argv + ["stop"]))
            self.assertFalse(os.path.exists(socket_path))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_start_without_model_or_health_only_fails(self):
        root = tempfile.mkdtemp(prefix="llm131-nomodel-")
        try:
            runtime = os.path.join(root, "run")
            self._owner_dir(runtime)
            argv = [
                "--checkout", CHECKOUT,
                "--runtime-dir", runtime,
                "--interpreter", sys.executable,
                "start",
            ]
            self.assertEqual(2, deploy.main(argv))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_isolated_temp_checkout_installs_fixture_pins(self):
        source = tempfile.mkdtemp(prefix="llm131-src-")
        work = tempfile.mkdtemp(prefix="llm131-iso-")
        try:
            daemon_src = os.path.join(source, "daemon")
            os.makedirs(daemon_src)
            for name in os.listdir(HERE):
                if name.startswith(".") or name == "__pycache__":
                    continue
                src = os.path.join(HERE, name)
                dst = os.path.join(daemon_src, name)
                if os.path.isdir(src):
                    if name in (".venv", ".local-run"):
                        continue
                    shutil.copytree(
                        src, dst,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                    )
                else:
                    shutil.copy2(src, dst)
            pin_path = os.path.join(daemon_src, "requirements-daemon.txt")
            with open(pin_path, "w", encoding="utf-8") as handle:
                handle.write("packaging==26.3\n")
            record = deploy.isolated_verify(
                source,
                work_dir=work,
                install_pins=True,
                python=sys.executable,
                timeout=20.0,
            )
            self.assertTrue(record["installed_pins"])
            self.assertEqual("health", record["health_kind"])
            self.assertFalse(record["model_loaded"])
            interpreter = record["interpreter"]
            self.assertTrue(os.path.isfile(interpreter))
            listing = subprocess.check_output(
                [interpreter, "-m", "pip", "show", "packaging"],
                text=True,
            )
            self.assertIn("Name: packaging", listing)
            self.assertIn("Version: 26.3", listing)
            with open(record["plist"], encoding="utf-8") as handle:
                rendered = handle.read()
            self.assertIsNone(HABIT_PATH.search(rendered))
            info = os.lstat(os.path.dirname(record["socket"]))
            self.assertEqual(0o700, stat.S_IMODE(info.st_mode))
        finally:
            shutil.rmtree(source, ignore_errors=True)
            shutil.rmtree(work, ignore_errors=True)

    def test_isolated_verify_skip_install_health_only(self):
        work = tempfile.mkdtemp(prefix="llm131-skip-")
        try:
            record = deploy.isolated_verify(
                CHECKOUT,
                work_dir=work,
                install_pins=False,
                timeout=15.0,
            )
            self.assertFalse(record["installed_pins"])
            self.assertEqual("health", record["health_kind"])
            self.assertFalse(record["model_loaded"])
            self.assertTrue(record["checkout"].startswith(work))
            self.assertTrue(record["runtime"].startswith(work))
            with open(record["plist"], encoding="utf-8") as handle:
                rendered = handle.read()
            self.assertIsNone(HABIT_PATH.search(rendered))
            self.assertIn(record["checkout"], rendered)
            self.assertIn(record["interpreter"], rendered)
            self.assertIn(record["model"], rendered)
            self.assertIn(record["socket"], rendered)
            self.assertIn(record["runtime"], rendered)
        finally:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
