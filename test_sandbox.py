#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
import unittest

from policy_gate import evaluate, load_policy
from sandbox import SandboxExecutor


HERE = os.path.dirname(os.path.abspath(__file__))


class PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = load_policy(os.path.join(HERE, "default_policy.json"))

    def test_registered_tool_allowed(self):
        self.assertEqual(evaluate(self.policy, "write_note", {"name": "safe.txt", "text": "ok"})[0], "ALLOW")

    def test_unknown_tool_denied(self):
        self.assertEqual(evaluate(self.policy, "shell", {"command": "whoami"})[0], "DENY")

    def test_path_escape_denied_before_allow(self):
        decision = evaluate(self.policy, "write_note", {"name": "../../escape", "text": "x"})
        self.assertEqual(decision[:2], ("DENY", "workspace_only"))


class NativeWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tower-test-")
        self.box = SandboxExecutor(self.temp.name, mode="native", timeout_seconds=2, enable_probes=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_native_is_not_overclaimed(self):
        self.assertFalse(self.box.describe()["hard_boundary"])

    def test_registered_write_and_digest(self):
        write = self.box.execute("write_note", {"name": "a.txt", "text": "exact"})
        self.assertTrue(write["ok"], write)
        digest = self.box.execute("sha256_note", {"name": "a.txt"})
        self.assertTrue(digest["ok"], digest)
        self.assertEqual(len(digest["result"]["sha256"]), 64)

    def test_escape_and_unknown_are_blocked(self):
        self.assertFalse(self.box.execute("write_note", {"name": "../../escape", "text": "x"})["ok"])
        self.assertFalse(self.box.execute("shell", {"command": "whoami"})["ok"])

    def test_secret_environment_not_inherited(self):
        old = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = "must-not-cross-boundary"
        try:
            result = self.box.execute("_probe_environment", {})
        finally:
            if old is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = old
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["secret_names_present"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
