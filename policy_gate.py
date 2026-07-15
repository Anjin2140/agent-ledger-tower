#!/usr/bin/env python3
"""
policy_gate.py — clearance authority for agent actions.

The ledger records what an agent DID. The gate decides whether an action is
allowed to run at all, BEFORE it executes, and records the decision (plus the
rule that fired) into the same tamper-evident ledger. So denials are auditable
and replayable too: the tower can prove not just what happened, but what it
refused to let happen.

Policy is DATA (see default_policy.json), not code — it can be inspected,
diffed, signed, and reimplemented in any language. Evaluation is deterministic:
the first matching deny rule wins; otherwise the policy default applies.

Rule 'when' conditions (all present ones must hold):
  tool          : exact tool-name match
  arg_contains  : case-insensitive substring anywhere in the arguments
  arg_matches   : regex, tested against the canonical args blob AND each string value
  arg_gt        : {"field": <name>, "limit": <number>}  numeric threshold

Stdlib only. Python 3.9+.
"""
from __future__ import annotations

import json
import re

from agent_ledger import encode_record, block_hash, canon


def load_policy(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _flatten_strings(obj):
    out = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out += _flatten_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out += _flatten_strings(v)
    return out


def _matches(rule, tool, args):
    w = rule.get("when", {})
    keys = ("tool", "arg_contains", "arg_matches", "arg_gt")
    if not any(k in w for k in keys):
        return False                       # never let a rule become an accidental catch-all
    if "tool" in w and w["tool"] != tool:
        return False

    blob = canon(args)
    values = _flatten_strings(args)

    if "arg_contains" in w:
        if str(w["arg_contains"]).lower() not in blob.lower():
            return False
    if "arg_matches" in w:
        pat = w["arg_matches"]
        if not (re.search(pat, blob) or any(re.search(pat, s) for s in values)):
            return False
    if "arg_gt" in w:
        spec = w["arg_gt"]
        val = args.get(spec["field"]) if isinstance(args, dict) else None
        try:
            if val is None or not (float(val) > float(spec["limit"])):
                return False
        except (TypeError, ValueError):
            return False
    return True


def evaluate(policy, tool, args):
    """Return (decision, rule_id, reason). Deterministic; first deny wins."""
    for rule in policy.get("rules", []):
        if rule.get("effect") == "deny" and _matches(rule, tool, args):
            return ("DENY", rule.get("id", "<rule>"), rule.get("reason", "denied by policy"))
    if str(policy.get("default", "allow")).lower() == "deny":
        return ("DENY", "default_deny", "no allow rule matched (default deny)")
    return ("ALLOW", "default_allow", "no deny rule matched")


def decision_record(step, tool, args, decision, rule, result, status):
    """Canonical, hashable record of one clearance decision + its outcome."""
    return {"step": step, "tool": tool, "args": canon(args),
            "decision": decision, "rule": rule,
            "result": canon(result), "status": status}


def make_block(index, ts, prev, record):
    """Encode a decision record and hash it into a ledger block."""
    payload = encode_record(record)
    h = block_hash(index, ts, prev, payload)
    block = {"index": index, "timestampMs": ts, "prevHash": prev,
             "stateKind": "gate_decision", "tool": record.get("tool", ""),
             "stateRcsHex": payload.hex(), "blockHash": h}
    return block, h
