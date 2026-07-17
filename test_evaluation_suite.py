#!/usr/bin/env python3
"""Regression checks for the checked-in deterministic evaluation corpus."""
from __future__ import annotations

import unittest

from evaluation_suite import DEFAULT_CASES, DEFAULT_POLICY, load_cases, run_cases
from policy_gate import load_policy


class EvaluationSuiteTests(unittest.TestCase):
    def test_checked_in_corpus_passes(self) -> None:
        results = run_cases(load_cases(DEFAULT_CASES), load_policy(DEFAULT_POLICY))
        self.assertEqual(len(results), 24)
        self.assertTrue(all(row["passed"] for row in results), results)

    def test_wrong_expectation_is_reported_as_a_failure(self) -> None:
        cases = {
            "response_quality": [],
            "policy": [{
                "id": "broken-expectation",
                "tool": "list_notes",
                "args": {},
                "expect": {"decision": "DENY", "rule": "default_deny"},
            }],
        }
        result = run_cases(cases, load_policy(DEFAULT_POLICY))[0]
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
