#!/usr/bin/env python3
"""
forgery_demo.py — shows the limit of a bare hash-chain and how an out-of-band
anchor closes it. No network, stdlib only.

  honest ledger -> seal an out-of-band anchor
  ATTACK A: rewrite the whole ledger from genesis (recompute EVERY hash)
  ATTACK B: truncate the last recorded action (rollback)
  for each: internal chain check vs anchor check
"""
from __future__ import annotations

import copy
import os

from agent_ledger import build_ledger, write_jsonl, AGENT_RUN
from agent_notary import anchor, verify_with_anchor

HERE = os.path.dirname(os.path.abspath(__file__))


def _p(name):
    return os.path.join(HERE, name)


def _rm(path):
    try:
        os.remove(path)
    except OSError:
        pass


def show(title, ledger, notary):
    r = verify_with_anchor(ledger, notary)
    print("  " + title)
    print("    internal chain : " + ("OK (self-consistent)" if r["internal_ok"] else "BROKEN") + " -- " + r["internal_reason"])
    print("    anchor check   : " + ("OK" if r["anchor_ok"] else "FORGERY DETECTED") + " -- " + r["anchor_reason"])
    return r


def main():
    line = "=" * 70
    honest = _p("forgery_ledger.jsonl")
    notary = _p("forgery_notary.log")
    _rm(notary)

    print(line)
    print("STRENGTHENED PROOF: hash-chain + out-of-band anchor")
    print(line)

    # 1) honest ledger + anchor
    blocks = build_ledger(AGENT_RUN)
    write_jsonl(blocks, honest)
    rec = anchor(honest, notary)
    print("\n[honest] recorded " + str(len(blocks)) + " actions, tail " + blocks[-1]["blockHash"][:12] + "..")
    print("[anchor] sealed out-of-band: len=" + str(rec["len"]) + " tail=" + rec["tail"][:12] + "..")
    print("\n(honest ledger — both checks should pass:)")
    show("honest", honest, notary)

    # 2) ATTACK A: full rewrite from genesis, every hash recomputed
    print("\n[ATTACK A] attacker rewrites the ENTIRE ledger from genesis")
    print("           (flips step 2 evidence 4->3, then recomputes every block hash)")
    forged_run = copy.deepcopy(AGENT_RUN)
    forged_run[2]["result"] = {"claims": 5, "evidence": 3}
    forged = build_ledger(forged_run)          # recomputes ALL hashes -> internally valid
    fpath = _p("forgery_ledger.rewritten.jsonl")
    write_jsonl(forged, fpath)
    show("rewritten-from-genesis", fpath, notary)
    _rm(fpath)

    # 3) ATTACK B: truncation / rollback
    print("\n[ATTACK B] attacker drops the last recorded action (rollback)")
    tpath = _p("forgery_ledger.truncated.jsonl")
    write_jsonl(blocks[:-1], tpath)
    show("truncated", tpath, notary)
    _rm(tpath)

    print("\n" + line)
    print("A bare hash-chain ACCEPTS both forgeries (each is internally consistent).")
    print("The out-of-band anchor REJECTS both. That is the difference that matters.")
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
