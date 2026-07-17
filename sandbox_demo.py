#!/usr/bin/env python3
"""
sandbox_demo.py — the OS boundary, demonstrated and recorded.

Runs a stream of actions through SandboxExecutor in the chosen tier. Each action
executes in a separate confined worker; effects that try to leave the mediated
tool interface are stopped and every verdict is written to the tamper-evident,
anchored ledger. Uses only the registered tools — no staged fake tools.

    python sandbox_demo.py --mode native   # soft dev tier (no Docker needed)
    python sandbox_demo.py --mode hard      # Docker hard boundary (fails closed if absent)
"""
from __future__ import annotations

import argparse
import json
import os

from agent_ledger import verify_chain, GENESIS, write_jsonl
from agent_notary import anchor, verify_with_anchor
from policy_gate import decision_record, make_block
from sandbox import SandboxExecutor, Grants

HERE = os.path.dirname(os.path.abspath(__file__))
JAIL = os.path.join(HERE, "sandbox_jail")

# (label, tool, args, fsize_mb, enable_probes)
SCENARIOS = [
    ("legit write (inside workspace)",   "write_note",        {"name": "ok.txt", "text": "hello"}, 25, False),
    ("escape the workspace (../../etc)", "write_note",        {"name": "../../etc/passwd", "text": "x"}, 25, False),
    ("unknown tool (shell)",             "shell",             {"command": "id"}, 25, False),
    ("oversize write (5MB vs 1MB cap)",  "write_note",        {"name": "big.bin", "size_kb": 5120}, 1, False),
    ("secret must not cross boundary",   "_probe_environment", {}, 25, True),
    ("legit large write (2MB, allowed)", "write_note",        {"name": "report.bin", "size_kb": 2048}, 25, False),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default=os.environ.get("AGENT_SANDBOX_MODE", "native"))
    mode = ap.parse_args().mode
    line = "=" * 74
    os.makedirs(JAIL, exist_ok=True)

    print(line)
    print("OS-LEVEL SANDBOX DEMO — tier=%s" % mode)
    probe = SandboxExecutor(JAIL, mode=mode)
    d = probe.describe()
    print("  tier=%s  hard_boundary=%s" % (d["tier"], d["hard_boundary"]))
    if not d["hard_boundary"]:
        print("  NOTE: " + d.get("reason", d.get("warning", "soft boundary")))
    print(line)

    # ensure there is a secret in the environment so the probe scenario is meaningful
    os.environ.setdefault("GEMINI_API_KEY", "demo-secret-must-not-cross")

    blocks, prev, t0 = [], GENESIS, 1_720_000_000_000
    print("  #  verdict    scenario                              detail")
    print("  -  --------   ------------------------------------  --------------------------")
    for step, (label, tool, args, fsize, probes) in enumerate(SCENARIOS):
        box = SandboxExecutor(JAIL, mode=mode, timeout_seconds=10,
                              enable_probes=probes, grants=Grants(fsize_mb=fsize))
        out = box.execute(tool, args)
        verdict = "EXECUTED" if out["ok"] else "BLOCKED"
        result = out["result"]
        rec = decision_record(step, tool, args, verdict, "os-sandbox",
                              result, out["status"], enforcement=out["enforcement"])
        ts = t0 + step * 1000
        block, h = make_block(step, ts, prev, rec)
        blocks.append(block)
        prev = h
        detail = (result.get("error") or json.dumps(result))[:38]
        print("  %d  %-9s  %-36s  %s" % (step, verdict, label, detail))

    ledger = os.path.join(HERE, "sandbox_ledger.jsonl")
    notary = os.path.join(HERE, "sandbox_notary.log")
    try:
        os.remove(notary)
    except OSError:
        pass
    write_jsonl(blocks, ledger)
    anchor(ledger, notary)
    ok, _, reason = verify_chain(ledger)
    va = verify_with_anchor(ledger, notary)
    print("")
    print("recorded %d sandbox verdicts -> %s" % (len(blocks), os.path.basename(ledger)))
    print("verify  : chain %s  |  anchor %s" % ("OK" if ok else "FAIL", "OK" if va["anchor_ok"] else "MISMATCH"))
    print("cross-check in another runtime: node verify.js sandbox_ledger.jsonl sandbox_notary.log")
    print(line)
    return 0 if (ok and va["anchor_ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
