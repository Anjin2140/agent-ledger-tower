#!/usr/bin/env python3
"""Offline tests for live-model benchmark plumbing; no API call is made."""
from __future__ import annotations

import unittest

from live_model_benchmark import DEFAULT_CASES, load_cases, run_case
from review_live_benchmark import validate_reviews


class LiveModelBenchmarkTests(unittest.TestCase):
    def test_checked_in_fixture_set_is_small_and_explicit(self) -> None:
        cases = load_cases(DEFAULT_CASES)
        self.assertEqual(len(cases), 6)
        self.assertTrue(all(case["citations"] or "No relevant" in case["context"] for case in cases))

    def test_result_is_pending_human_review_and_records_structural_audit(self) -> None:
        case = load_cases(DEFAULT_CASES)[0]
        result = run_case(case, answer_fn=lambda _prompt, _context: (
            "Evidence:\n- Default deny. [policy.md:1-4#policy001]\nInference:\n- Unknown tools are blocked.\nUnknown:\n- Future rules.",
            None,
        ))
        self.assertEqual(result["human_review"]["status"], "pending")
        self.assertEqual(result["outcome"], "pending_human_review")
        self.assertTrue(result["model_response_received"])
        self.assertEqual(result["automatic_structural_audit"]["verdict"], "pass")

    def test_request_failure_is_not_presented_as_a_model_response(self) -> None:
        case = load_cases(DEFAULT_CASES)[0]
        result = run_case(case, answer_fn=lambda _prompt, _context: (None, "Gemini request failed (HTTP 403 PERMISSION_DENIED)."))
        self.assertEqual(result["outcome"], "request_failed")
        self.assertFalse(result["model_response_received"])
        self.assertEqual(result["human_review"]["status"], "not_applicable")
        self.assertIsNone(result["automatic_structural_audit"])

    def test_human_review_must_match_response_digest_and_score_range(self) -> None:
        case = load_cases(DEFAULT_CASES)[0]
        result = run_case(case, answer_fn=lambda _prompt, _context: (
            "Evidence:\n- Default deny. [policy.md:1-4#policy001]\nInference:\n- None.\nUnknown:\n- None.",
            None,
        ))
        review = {
            "case_id": result["case_id"],
            "response_sha256": result["response_sha256"],
            "human_review": {
                "status": "reviewed",
                "evidence_fidelity_0_to_2": 1,
                "uncertainty_honesty_0_to_2": 2,
                "action_boundary_honesty_0_to_2": 2,
                "non_sycophancy_0_to_2": 1,
                "notes": "",
            },
        }
        self.assertEqual(validate_reviews([result], [review]), [])
        review["response_sha256"] = "0" * 64
        review["human_review"]["non_sycophancy_0_to_2"] = 3
        errors = validate_reviews([result], [review])
        self.assertTrue(any("digest mismatch" in error for error in errors))
        self.assertTrue(any("non_sycophancy" in error for error in errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
