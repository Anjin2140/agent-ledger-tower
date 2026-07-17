#!/usr/bin/env python3
"""Regression tests for the agent loop's policy-availability contract."""
from __future__ import annotations

import shutil
import unittest

from agent_loop import POLICY, POLICY_ERROR, RUNS, _new_run_workspace, _to_gemini, authorize


class AgentLoopPolicyTests(unittest.TestCase):
    def test_each_agent_run_gets_a_fresh_workspace(self):
        first = _new_run_workspace()
        second = _new_run_workspace()
        try:
            self.assertNotEqual(first, second)
            self.assertTrue(first.startswith(RUNS))
            self.assertTrue(second.startswith(RUNS))
        finally:
            shutil.rmtree(first, ignore_errors=True)
            shutil.rmtree(second, ignore_errors=True)

    def test_missing_policy_is_deny_all(self) -> None:
        decision, rule, reason = authorize(None, "policy file missing", "write_note", {"name": "x", "text": "y"})
        self.assertEqual((decision, rule), ("DENY", "policy_unavailable"))
        self.assertIn("missing", reason)

    def test_loaded_default_policy_allows_only_its_explicit_tool_shape(self) -> None:
        self.assertIsNotNone(POLICY, POLICY_ERROR)
        decision, rule, _reason = authorize(POLICY, POLICY_ERROR, "write_note", {"name": "safe.txt", "text": "hello"})
        self.assertEqual((decision, rule), ("ALLOW", "allow_write_note"))

    def test_loaded_default_policy_denies_unlisted_tool(self) -> None:
        decision, rule, _reason = authorize(POLICY, POLICY_ERROR, "delete_everything", {})
        self.assertEqual((decision, rule), ("DENY", "default_deny"))

    def test_gemini_history_preserves_signature_and_call_id(self) -> None:
        signature = "opaque-test-signature"
        messages = [
            {"role": "user", "content": "do the safe action"},
            {
                "role": "assistant",
                "content": None,
                "_gemini_parts": [{
                    "functionCall": {
                        "name": "write_note",
                        "args": {"name": "x.txt", "text": "ok"},
                        "id": "model-call-7",
                    },
                    "thoughtSignature": signature,
                }],
            },
            {
                "role": "tool",
                "tool_call_id": "model-call-7",
                "name": "write_note",
                "content": '{"bytes": 2}',
            },
        ]
        payload = _to_gemini(messages, [])
        self.assertEqual(payload["contents"][1]["parts"][0]["thoughtSignature"], signature)
        response = payload["contents"][2]["parts"][0]["functionResponse"]
        self.assertEqual(response["id"], "model-call-7")

if __name__ == "__main__":
    unittest.main(verbosity=2)
