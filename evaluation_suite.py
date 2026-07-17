#!/usr/bin/env python3
"""Run the fixed, deterministic control-tower evaluation corpus.

The corpus tests two enforceable contracts:

1. response reviewability (structure, use of supplied citations, no impossible
   action claims in read-only chat); and
2. policy adjudication (default deny plus hostile argument patterns).

It does not claim to evaluate a model's factual knowledge, beliefs, or general
intelligence. No model, key, network, or sandbox is needed to run this suite.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from policy_gate import evaluate, load_policy
from response_quality import audit_response


HERE = Path(__file__).resolve().parent
DEFAULT_CASES = HERE / "evaluation_cases.json"
DEFAULT_POLICY = HERE / "default_policy.json"


def _result(case_id: str, domain: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"id": case_id, "domain": domain, "passed": passed, "detail": detail}


def run_cases(cases: dict[str, Any], policy: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate the checked-in corpus and return one result per case."""
    results: list[dict[str, Any]] = []
    for case in cases.get("response_quality", []):
        expected = case["expect"]
        report = audit_response(case["text"], case.get("citations", []))
        missing = [flag for flag in expected.get("flags_include", []) if flag not in report["flags"]]
        passed = report["verdict"] == expected["verdict"] and not missing
        detail = "verdict=" + report["verdict"] + " flags=" + (",".join(report["flags"]) or "none")
        results.append(_result(case["id"], "response_quality", passed, detail))

    for case in cases.get("policy", []):
        expected = case["expect"]
        decision, rule, _reason = evaluate(policy, case["tool"], case["args"])
        passed = decision == expected["decision"] and rule == expected["rule"]
        detail = f"decision={decision} rule={rule}"
        results.append(_result(case["id"], "policy", passed, detail))
    return results


def load_cases(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("schema") != "agent-ledger-tower-evaluations-v1":
        raise ValueError("unsupported evaluation corpus schema")
    return data


def print_results(results: Iterable[dict[str, Any]], quiet: bool = False) -> bool:
    rows = list(results)
    failed = [row for row in rows if not row["passed"]]
    if not quiet:
        print("CONTROL-TOWER EVALUATION CORPUS")
        print("=" * 70)
        for row in rows:
            status = "PASS" if row["passed"] else "FAIL"
            print(f"  [{status}] {row['id']:<28} {row['detail']}")
        print("=" * 70)
    print(f"RESULT: {len(rows) - len(failed)}/{len(rows)} cases passed")
    return not failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic response-quality and policy evaluation cases")
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    return 0 if print_results(run_cases(load_cases(args.cases), load_policy(args.policy)), args.quiet) else 1


if __name__ == "__main__":
    raise SystemExit(main())
