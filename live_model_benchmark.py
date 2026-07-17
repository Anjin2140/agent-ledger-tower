#!/usr/bin/env python3
"""Run fixed, human-scored model-behavior checks against the read-only chat path.

Default mode is a dry run: it never sends a request. ``--live`` submits only
the six harmless fixtures in ``live_benchmark_cases.json`` to the configured
Gemini model. The result file intentionally includes the raw response so a
human can score factuality and sycophancy; it is a local ``.jsonl`` artifact
and is ignored by version control.

Automatic response-quality flags are useful evidence, but they are not a model
truth score. Use ``review_live_benchmark.py`` afterward for the human record.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from chat_console import MODEL, gemini_answer
from response_quality import audit_response


HERE = Path(__file__).resolve().parent
DEFAULT_CASES = HERE / "live_benchmark_cases.json"
DEFAULT_OUTPUT = HERE / "live_benchmark_results.jsonl"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("schema") != "agent-ledger-tower-live-benchmark-v1":
        raise ValueError("unsupported live benchmark schema")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("benchmark contains no cases")
    return cases


def run_case(case: dict[str, Any], answer_fn=gemini_answer) -> dict[str, Any]:
    """Call the configured read-only model once and produce a pending-review row."""
    answer, error = answer_fn(case["prompt"], case["context"])
    text = answer or ""
    citations = case.get("citations", [])
    request_failed = answer is None
    return {
        "schema": "agent-ledger-tower-live-result-v1",
        "outcome": "request_failed" if request_failed else "pending_human_review",
        "model_response_received": not request_failed,
        "case_id": case["id"],
        "model": MODEL,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "prompt_sha256": sha256_text(case["prompt"]),
        "context_sha256": sha256_text(case["context"]),
        "citations": citations,
        "review_focus": case["review_focus"],
        "response": text,
        "response_sha256": sha256_text(text),
        "request_error": error,
        "automatic_structural_audit": audit_response(text, citations) if answer is not None else None,
        "human_review": {
            "status": "not_applicable" if request_failed else "pending",
            "evidence_fidelity_0_to_2": None,
            "uncertainty_honesty_0_to_2": None,
            "action_boundary_honesty_0_to_2": None,
            "non_sycophancy_0_to_2": None,
            "notes": ""
        }
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Human-scored live-model benchmark (dry run by default)")
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--live", action="store_true", help="send the checked-in harmless fixtures to Gemini")
    args = parser.parse_args(argv)
    cases = load_cases(args.cases)
    if not args.live:
        print(f"DRY RUN: {len(cases)} fixed cases loaded; no model call was made.")
        print("Review focus: evidence fidelity, uncertainty honesty, action-boundary honesty, non-sycophancy.")
        print("Use --live only when you intend to spend API quota on these fixtures.")
        return 0
    if not os.environ.get("GEMINI_API_KEY"):
        print("LIVE RUN REFUSED: GEMINI_API_KEY is not present in this process environment.")
        return 2

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    failed_requests = 0
    with output.open("w", encoding="utf-8") as handle:
        for case in cases:
            row = run_case(case)
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            if row["outcome"] == "request_failed":
                failed_requests += 1
                state = "REQUEST_FAILED"
            else:
                state = row["automatic_structural_audit"]["verdict"]
            print(f"[{state.upper()}] {case['id']}")
    if failed_requests:
        print(f"Wrote {len(cases)} rows to {output}, but {failed_requests} request(s) failed.")
        print("Benchmark is incomplete: do not score blank or failed rows as model behavior.")
        print("Inspect the safe request_error field, correct the configuration, then rerun --live.")
        return 1
    print(f"Wrote {len(cases)} pending human-review rows to {output}")
    print("Next: py -3.13 review_live_benchmark.py --input " + str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
