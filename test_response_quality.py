#!/usr/bin/env python3
"""Tests for the response-quality contract; no model or network is required."""
from __future__ import annotations

import unittest

from response_quality import audit_response


class ResponseQualityTests(unittest.TestCase):
    def test_cited_structured_response_is_reviewable(self) -> None:
        citation = "facts.md:1-2#abc123"
        report = audit_response(
            "Evidence:\n- The gate denies unsafe tools. [facts.md:1-2#abc123]\n"
            "Inference:\n- The gate can prevent this proposed call.\n"
            "Unknown:\n- Whether the policy is complete for all tools.",
            [citation],
        )
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["used_citation_count"], 1)

    def test_uncited_response_is_flagged_when_sources_exist(self) -> None:
        report = audit_response(
            "Evidence: The system is safe.\nInference: It will always work.\nUnknown: none.",
            ["facts.md:1-2#abc123"],
        )
        self.assertIn("no_supplied_citation_used", report["flags"])

    def test_read_only_action_claim_is_flagged(self) -> None:
        report = audit_response(
            "Evidence: I wrote the requested file.\nInference: It is ready.\nUnknown: none.",
            ["facts.md:1-2#abc123"],
        )
        self.assertIn("action_claim_in_read_only_chat", report["flags"])

    def test_no_source_answer_must_name_the_unknown(self) -> None:
        report = audit_response(
            "Evidence: No local source was supplied.\nInference: None.\nUnknown: The answer cannot be determined from the available evidence.",
            [],
        )
        self.assertEqual(report["verdict"], "pass")


if __name__ == "__main__":
    unittest.main(verbosity=2)
