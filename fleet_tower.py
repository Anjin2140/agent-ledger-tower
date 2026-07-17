#!/usr/bin/env python3
"""
fleet_tower.py — one control tower over many agents.

Each agent flies its own tamper-evident, anchored ledger. The tower audits the
whole fleet and does NOT trust each agent's own gate: it independently
re-adjudicates every recorded action against the fleet policy, reading the
authoritative hashed payload (decode_record). It catches two kinds of rogue:

  * a TAMPERED agent    — ledger rewritten/rolled back      -> chain/anchor fails
  * a MISBEHAVING agent — bypassed its gate and executed a
                          forbidden action                  -> re-adjudication fails

An operator can KILL an agent (drop a KILL sentinel); a killed agent halts on its
next launch instead of acting. No network, stdlib only.
"""
from __future__ import annotations

import json
import os
import re

from agent_ledger import verify_chain, decode_record, GENESIS, write_jsonl
from agent_notary import anchor, verify_with_anchor
from policy_gate import load_policy, evaluate, decision_record, make_block
from sandbox import SandboxExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
FLEET = os.path.join(HERE, "fleet")
SANDBOX_MODE = os.environ.get("AGENT_SANDBOX_MODE", "hard")
AGENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


# --- operator kill switch ----------------------------------------------------
def validate_agent_id(agent_id: str) -> str:
    """Reject path-like identifiers before they can reach the fleet filesystem."""
    if not isinstance(agent_id, str) or not AGENT_ID.fullmatch(agent_id):
        raise ValueError("agent id must contain only letters, numbers, '.', '_', or '-'")
    return agent_id


def kill_path(agent_id):
    return os.path.join(FLEET, validate_agent_id(agent_id), "KILL")


def is_killed(agent_id):
    return os.path.exists(kill_path(agent_id))


# --- a minimal gated agent that writes its own ledger + anchor --------------
def _build(agent_id, proposals, policy, gate=True):
    agent_dir = os.path.join(FLEET, agent_id)
    work_dir = os.path.join(agent_dir, "work")
    os.makedirs(work_dir, exist_ok=True)
    ledger = os.path.join(agent_dir, "ledger.jsonl")
    sandbox = SandboxExecutor(work_dir, mode=SANDBOX_MODE)

    # an operator kill grounds the agent: it records a halt and does nothing else
    if is_killed(agent_id):
        proposals = [("__halt__", {"by": "operator"})]

    blocks, prev, t0 = [], GENESIS, 1_720_000_000_000
    for step, (tool, args) in enumerate(proposals):
        if tool == "__halt__":
            decision, rule, why = "HALTED", "operator_kill", "grounded by operator"
            result, status = {"halted": True}, "halted"
            enforcement = {"selected": "not_executed", "reason": "operator_kill"}
        elif gate:
            decision, rule, why = evaluate(policy, tool, args)
            if decision == "DENY":
                result, status = {"blocked": True, "reason": why}, "denied"
                enforcement = {"selected": "not_executed", "reason": "policy_denied"}
            else:
                outcome = sandbox.execute(tool, args)
                result, status = outcome["result"], outcome["status"]
                enforcement = outcome["enforcement"]
        else:
            # Test fixture: claim an unmediated execution. No host action is
            # actually launched; the tower must reject the missing boundary.
            decision, rule, why = "ALLOW", "gate_bypassed", "claimed execution without clearance"
            result, status = {"claimed_executed": True}, "ok"
            enforcement = {"selected": "bypass", "hard_boundary": False}
        rec = decision_record(step, tool, args, decision, rule, result, status,
                              enforcement=enforcement)
        ts = t0 + step * 1000
        block, h = make_block(step, ts, prev, rec)
        blocks.append(block)
        prev = h
    return ledger, blocks


def run_agent(agent_id, proposals, policy, gate=True):
    ledger, blocks = _build(agent_id, proposals, policy, gate)
    write_jsonl(blocks, ledger)
    notary = os.path.join(FLEET, agent_id, "notary.log")
    try:
        os.remove(notary)
    except OSError:
        pass
    anchor(ledger, notary)          # honest anchor sealed once, out of band
    return ledger, notary


def forge_rewrite(agent_id, proposals, policy):
    """Rewrite an agent's ledger from genesis (valid internal chain) but leave its
    already-sealed anchor untouched — the tamper a naive chain would miss."""
    ledger, blocks = _build(agent_id, proposals, policy, gate=True)
    write_jsonl(blocks, ledger)     # NOTE: deliberately do not re-anchor


# --- the tower: audit every agent independently -----------------------------
def audit_agent(ledger, notary, policy):
    ok, _idx, reason = verify_chain(ledger)
    if not ok:
        return {"status": "FLAG", "reason": "chain broken: " + reason}
    va = verify_with_anchor(ledger, notary)
    if not va["anchor_ok"]:
        return {"status": "FLAG", "reason": "tamper: " + va["anchor_reason"]}

    blocks = [json.loads(l) for l in open(ledger, encoding="utf-8") if l.strip()]
    denied = 0
    viol = None
    for b in blocks:
        rec = decode_record(bytes.fromhex(b["stateRcsHex"]))
        args = json.loads(rec["args"])
        d, vrule, _why = evaluate(policy, rec["tool"], args)
        try:
            enforcement = json.loads(rec.get("enforcement", "{}"))
        except (TypeError, json.JSONDecodeError):
            enforcement = {}
        if rec["status"] == "denied":
            denied += 1
        elif d == "DENY" and viol is None:
            viol = "executed '" + rec["tool"] + "' that policy denies (" + vrule + ")"
        elif rec["status"].startswith("sandbox_") and viol is None:
            viol = "hard sandbox did not execute '" + rec["tool"] + "' (" + rec["status"] + ")"
        elif rec["status"] == "ok" and rec["decision"] == "ALLOW" and not enforcement.get("hard_boundary") and viol is None:
            viol = "unconfined execution claimed for '" + rec["tool"] + "'"
    if viol:
        return {"status": "FLAG", "reason": "policy violation: " + viol}
    return {"status": "OK", "reason": "", "n": len(blocks), "denied": denied}


SAFE = [("write_note", {"name": "a.txt", "text": "hello"}), ("list_notes", {})]

FLEET_PLAN = {
    "agent-01": {"proposals": SAFE + [("write_note", {"name": "b.txt", "text": "ok"})], "gate": True},
    "agent-02": {"proposals": SAFE + [("http_get", {"url": "https://arxiv.org/abs/2606.11632", "verify": False})], "gate": True},
    "agent-03": {"proposals": SAFE + [("write_note", {"name": "c.txt", "text": "ok"})], "gate": True},
    "agent-04": {"proposals": [("http_get", {"url": "http://evil", "verify": False}), ("list_notes", {})], "gate": False},
    "agent-05": {"proposals": SAFE, "gate": True},
}


def launch():
    """Build the whole fleet (honoring any operator kills) + inject the tamper rogue."""
    policy = load_policy(os.path.join(HERE, "default_policy.json"))
    os.makedirs(FLEET, exist_ok=True)
    for aid, plan in FLEET_PLAN.items():
        run_agent(aid, plan["proposals"], policy, plan["gate"])
    # agent-03 is tampered only if it wasn't grounded by the operator
    if not is_killed("agent-03"):
        forge_rewrite("agent-03", SAFE + [("write_note", {"name": "c.txt", "text": "TAMPERED"})], policy)


def main():
    line = "=" * 70
    policy = load_policy(os.path.join(HERE, "default_policy.json"))
    launch()

    print(line)
    print("FLEET TOWER — auditing " + str(len(FLEET_PLAN)) + " agents")
    print(line)
    print("  agent      status  detail")
    print("  ---------  ------  --------------------------------------------------")
    flagged = []
    for aid in sorted(FLEET_PLAN):
        ledger = os.path.join(FLEET, aid, "ledger.jsonl")
        notary = os.path.join(FLEET, aid, "notary.log")
        r = audit_agent(ledger, notary, policy)
        if r["status"] == "OK":
            extra = str(r["n"]) + " actions" + ((", " + str(r["denied"]) + " denied-blocked") if r["denied"] else "")
        else:
            extra = r["reason"]
            flagged.append(aid)
        print("  %-9s  %-6s  %s" % (aid, r["status"], extra))

    print("")
    print("FLEET: " + str(len(FLEET_PLAN) - len(flagged)) + " flying clear, "
          + str(len(flagged)) + " GROUNDED -> " + (", ".join(flagged) if flagged else "none"))
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
