#!/usr/bin/env python3
"""
agent_notary.py — out-of-band anchor for the agent ledger.

A hash-linked chain proves nothing against an attacker who controls the whole
file: they can rewrite every block from genesis, recompute every hash, and the
chain still verifies internally. The defense is an anchor recorded OUT OF BAND —
somewhere the attacker cannot retroactively edit (an append-only log shipped
off-box, an external timestamping service, a public chain, or even a printed
hash). Checking against that anchor catches:
  * full rewrite from genesis  (tail hash won't match the anchored tail)
  * truncation / rollback      (length + tail won't match)

In this demo the anchor is a SEPARATE append-only file. Its security rests
entirely on that file being outside the attacker's reach: the code makes the
check, the deployment makes the file trustworthy. That distinction is stated
plainly on purpose — no overclaim.

Stdlib only. Python 3.9+.
"""
from __future__ import annotations

import json
import os
import time

from agent_ledger import verify_chain


def _load_blocks(ledger_path):
    return [json.loads(l) for l in open(ledger_path, encoding="utf-8") if l.strip()]


def anchor(ledger_path, notary_path, now_ms=None):
    """Seal the current ledger tail into the out-of-band notary log."""
    blocks = _load_blocks(ledger_path)
    if not blocks:
        raise ValueError("cannot anchor an empty ledger")
    rec = {"anchoredAtMs": int(now_ms if now_ms is not None else time.time() * 1000),
           "len": len(blocks), "tail": blocks[-1]["blockHash"]}
    with open(notary_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def latest_anchor(notary_path):
    recs = [json.loads(l) for l in open(notary_path, encoding="utf-8") if l.strip()]
    if not recs:
        raise ValueError("no anchor records")
    return recs[-1]


def verify_with_anchor(ledger_path, notary_path):
    """Two independent checks: internal chain integrity AND agreement with the
    out-of-band anchor. anchor_ok=False signals forgery even when the internal
    chain is perfectly self-consistent."""
    internal_ok, _idx, internal_reason = verify_chain(ledger_path)
    a = latest_anchor(notary_path)
    blocks = _load_blocks(ledger_path)
    tail = blocks[-1]["blockHash"] if blocks else None
    if len(blocks) != a["len"]:
        anchor_ok = False
        anchor_reason = "length " + str(len(blocks)) + " != anchored " + str(a["len"]) + " (truncation/extension)"
    elif tail != a["tail"]:
        anchor_ok = False
        anchor_reason = "tail " + (tail[:12] if tail else "none") + ".. != anchored " + a["tail"][:12] + ".. (rewrite)"
    else:
        anchor_ok = True
        anchor_reason = "matches anchor (len=" + str(a["len"]) + ", tail=" + a["tail"][:12] + "..)"
    return {"internal_ok": internal_ok, "internal_reason": internal_reason,
            "anchor_ok": anchor_ok, "anchor_reason": anchor_reason, "anchor": a}
