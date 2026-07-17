#!/usr/bin/env python3
"""
agent_loop.py — a REAL agent loop whose every action is recorded into the
deterministic, tamper-evident ledger.

The model is called through Google's Gemini REST API using the Python standard
library. On Windows, a narrowly allowlisted PowerShell helper can use the OS
certificate verifier when Python rejects an otherwise Windows-trusted local CA.
There are no third-party Python packages to install. If a key or network is
absent, an explicitly permitted deterministic mock can still prove the loop and
ledger mechanics offline.

To run against REAL Gemini (on a machine with network):
    setx GEMINI_API_KEY "...your key..."      (then open a NEW terminal)
    set  AGENT_MODEL=gemini-3.1-flash-lite    (optional model override)
    py -3.13 agent_loop.py

The ledger records the ACTIONS, not the model — so the audit trail is identical
whichever model produced it. To use a different provider, replace call_model();
everything downstream (recording, hashing, verification) is provider-agnostic.

Security: TLS certificate verification is mandatory. The Windows compatibility
path uses the OS verifier and a fixed Gemini destination; it is not a bypass.
This program deliberately has no switch that disables TLS verification.

Stdlib only. Python 3.9+.
"""
from __future__ import annotations

import json
import os
import tempfile

# Optional .env support (only if python-dotenv happens to be installed).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from agent_ledger import (encode_record, decode_record, block_hash, verify_chain, GENESIS,
                          action_record, write_jsonl)
from agent_notary import anchor, verify_with_anchor
from gemini_config import configured_model, gemini_json_request, get_api_key, safe_model_error
from policy_gate import load_policy, evaluate, decision_record
from sandbox import SandboxExecutor


MODEL = configured_model("AGENT_MODEL")

# CLEARANCE: policy availability is itself a security condition. A missing or
# malformed policy must never turn into implicit authority for the model.
_POLICY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "default_policy.json")
POLICY = None
POLICY_ERROR = ""
try:
    if not os.path.exists(_POLICY_PATH):
        POLICY_ERROR = "default policy file is missing"
    else:
        POLICY = load_policy(_POLICY_PATH)
except (OSError, ValueError, TypeError) as exc:
    POLICY_ERROR = "default policy could not be loaded: " + type(exc).__name__

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "agent_work")
os.makedirs(WORK, exist_ok=True)
RUNS = os.path.join(WORK, "runs")
os.makedirs(RUNS, exist_ok=True)
SANDBOX_MODE = os.environ.get("AGENT_SANDBOX_MODE", "hard")
# Allow a little Docker cold-start time while retaining a strict per-action
# bound. The lower-level SandboxExecutor default remains five seconds for
# direct diagnostics; the agent path has the additional container startup cost.
ACTION_TIMEOUT_SECONDS = 10.0
SANDBOX = SandboxExecutor(WORK, mode=SANDBOX_MODE)


def _new_run_workspace() -> str:
    """Create a fresh workspace so one model run cannot see another run's files."""
    return tempfile.mkdtemp(prefix="run-", dir=RUNS)


def authorize(policy: dict | None, policy_error: str, tool: str, args: dict) -> tuple[str, str, str]:
    """Return a pre-execution decision; unavailable policy always denies.

    Keeping this small function separate makes the failure mode testable without
    invoking a model or a sandbox. The policy file is required authorization,
    not an optional convenience setting.
    """
    if policy is None:
        return ("DENY", "policy_unavailable", policy_error or "no policy is loaded")
    return evaluate(policy, tool, args)


# --- tool descriptions (execution occurs only in sandbox_worker.py) ---------
TOOL_SCHEMA = [
    {"type": "function", "function": {"name": "write_note",
        "description": "Write a text note to the workspace.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "text": {"type": "string"}}, "required": ["name", "text"]}}},
    {"type": "function", "function": {"name": "sha256_note",
        "description": "Return the SHA-256 of a note.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "list_notes",
        "description": "List notes in the workspace.",
        "parameters": {"type": "object", "properties": {}}}},
]


# --- model interface: direct Gemini REST (stdlib) with a mock fallback -------
MOCK_SCRIPT = [
    {"name": "write_note", "args": {"name": "sab_summary.txt",
        "text": "SAB is a certificate-bound admission boundary for agent actions (He & Yu 2026)."}},
    {"name": "sha256_note", "args": {"name": "sab_summary.txt"}},
    {"name": "list_notes", "args": {}},
]


def mock_model(messages, tools):
    done = sum(1 for m in messages if m.get("role") == "tool")
    if done < len(MOCK_SCRIPT):
        tc = MOCK_SCRIPT[done]
        return {"content": None, "tool_calls": [{"id": f"call_{done}", "name": tc["name"], "args": tc["args"]}]}
    return {"content": "Done: wrote sab_summary.txt, checksummed it, and listed the workspace.", "tool_calls": []}


def _to_gemini(messages, tools):
    """Translate OpenAI-style messages/tools into Gemini generateContent format."""
    gemini_tools = []
    if tools:
        funcs = [{"name": t["function"]["name"],
                  "description": t["function"].get("description", ""),
                  "parameters": t["function"].get("parameters", {})}
                 for t in tools if t.get("type") == "function"]
        if funcs:
            gemini_tools = [{"functionDeclarations": funcs}]

    contents = []
    for m in messages:
        if m["role"] == "tool":
            # a tool result -> Gemini functionResponse (carries the real tool name)
            function_response = {
                "name": m.get("name", "tool"),
                "response": {"result": m.get("content", "")},
            }
            # Gemini 3 validates function responses against the exact call ID.
            # Older models tolerate its absence, but preserving it is harmless.
            if m.get("tool_call_id"):
                function_response["id"] = m["tool_call_id"]
            fr = {"functionResponse": function_response}
            contents.append({"role": "user", "parts": [fr]})
            continue

        if m["role"] in ("user", "system"):
            parts = []
            if m.get("content"):
                parts.append({"text": m["content"]})
            contents.append({"role": "user", "parts": parts})
            continue

        # assistant turn
        # Gemini 3 function calls carry an encrypted thoughtSignature.  The
        # REST API requires the complete model parts to be echoed verbatim on
        # the next turn; reconstructing only name/args causes HTTP 400.
        if m.get("_gemini_parts") is not None:
            contents.append({"role": "model", "parts": m["_gemini_parts"]})
            continue
        parts = []
        if m.get("content"):
            parts.append({"text": m["content"]})
        for tc in (m.get("tool_calls") or []):        # preserve real function calls
            fn = tc["function"]
            parts.append({"functionCall": {
                "name": fn["name"],
                "args": json.loads(fn.get("arguments") or "{}")}})
        contents.append({"role": "model", "parts": parts})

    payload = {"contents": contents}
    if gemini_tools:
        payload["tools"] = gemini_tools
    return payload


def call_model(messages: list, tools: list) -> dict:
    """Call Gemini. Mock use is available only when explicitly enabled."""
    if os.environ.get("AGENT_FORCE_MOCK") == "1":
        return {"_mock_reason": "explicit", **mock_model(messages, tools)}
    api_key = get_api_key()
    if not api_key:
        if os.environ.get("AGENT_ALLOW_MOCK") == "1":
            return {"_mock_reason": "missing_key", **mock_model(messages, tools)}
        raise RuntimeError("GEMINI_API_KEY is not configured. Run gemini_preflight.py before a live agent run.")
    try:
        raw_model = MODEL.split("/", 1)[1] if "/" in MODEL else MODEL
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               + raw_model + ":generateContent")

        body = gemini_json_request(url, api_key, _to_gemini(messages, tools), timeout=30)

        cands = body.get("candidates") or []
        if not cands:
            raise ValueError("no candidates returned: " + str(body))

        raw_msg = {"role": "assistant", "content": None, "_gemini_parts": []}
        tcs, oai_calls = [], []
        for part in cands[0].get("content", {}).get("parts", []):
            # Keep the exact response parts, including Gemini 3 thought
            # signatures, for the next stateless REST request.
            raw_msg["_gemini_parts"].append(part)
            if "text" in part and part["text"]:
                raw_msg["content"] = (raw_msg["content"] or "") + part["text"]
            if "functionCall" in part:
                fc = part["functionCall"]
                tc_id = fc.get("id") or "call_" + fc["name"]
                args = fc.get("args", {}) or {}
                tcs.append({"id": tc_id, "name": fc["name"], "args": args})
                oai_calls.append({"id": tc_id, "type": "function",
                                  "function": {"name": fc["name"], "arguments": json.dumps(args)}})
        if oai_calls:
            raw_msg["tool_calls"] = oai_calls
        return {"content": raw_msg.get("content"), "tool_calls": tcs, "_raw": raw_msg}

    except Exception as e:
        if os.environ.get("AGENT_ALLOW_MOCK") == "1":
            return {"_mock_reason": type(e).__name__, **mock_model(messages, tools)}
        raise RuntimeError(safe_model_error(e)) from None


# --- the agent loop, recording every action into the ledger -----------------
def run(task: str, max_turns: int = 8):
    messages = [
        {"role": "system", "content": (
            "You are a careful agent. Use the tools to complete the task, then stop. "
            "This run has a fresh isolated workspace; use relative filenames only."
        )},
        {"role": "user", "content": task},
    ]
    blocks, prev, step, t0 = [], GENESIS, 0, 1_720_000_000_000
    used_mock = None
    run_sandbox = SandboxExecutor(
        _new_run_workspace(), mode=SANDBOX_MODE,
        timeout_seconds=ACTION_TIMEOUT_SECONDS,
    )

    for _ in range(max_turns):
        out = call_model(messages, TOOL_SCHEMA)
        if used_mock is None:
            used_mock = "_mock_reason" in out
        if not out["tool_calls"]:
            print("  [model claim; untrusted] " + (out.get("content") or "").strip()[:80])
            break
        # thread the assistant turn (real functionCalls preserved for the next request)
        messages.append(out.get("_raw") or {"role": "assistant", "content": None,
            "tool_calls": [{"id": tc["id"], "type": "function",
                            "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}}
                           for tc in out["tool_calls"]]})
        for tc in out["tool_calls"]:
            # CLEARANCE: the tower decides BEFORE the action runs.
            decision, rule, why = authorize(POLICY, POLICY_ERROR, tc["name"], tc["args"])
            if decision == "DENY":
                result, status = {"blocked": True, "reason": why}, "denied"
                enforcement = {"selected": "not_executed", "reason": "policy_denied"}
            else:
                outcome = run_sandbox.execute(tc["name"], tc["args"])
                result = outcome["result"]
                status = outcome["status"]
                enforcement = outcome["enforcement"]
            # RECORD the decision + outcome into the tamper-evident ledger
            payload = encode_record(decision_record(step, tc["name"], tc["args"],
                                                    decision, rule, result, status,
                                                    enforcement=enforcement))
            ts = t0 + step * 1000
            h = block_hash(step, ts, prev, payload)
            blocks.append({"index": step, "timestampMs": ts, "prevHash": prev,
                           "stateKind": "gate_decision", "tool": tc["name"],
                           "stateRcsHex": payload.hex(), "blockHash": h})
            prev = h
            print("  [" + str(step) + "] POLICY " + decision + " (" + rule + ") "
                  + tc["name"] + " -> " + status + " " + json.dumps(result)[:40]
                  + "  block " + h[:12] + "...")
            messages.append({"role": "tool", "tool_call_id": tc["id"],
                             "name": tc["name"], "content": json.dumps(result)})
            step += 1
    return blocks, used_mock


def main() -> int:
    line = "=" * 70
    print(line)
    print("AGENT LOOP -> TAMPER-EVIDENT LEDGER  (Gemini via stdlib REST)")
    print(line)
    print("model target: " + MODEL)
    if POLICY is None:
        print("policy      : UNAVAILABLE — every proposed action will be denied (" + POLICY_ERROR + ")")
    sandbox_report = SANDBOX.describe()
    print("sandbox     : " + sandbox_report["tier"] + " (requested=" + SANDBOX_MODE + ")")
    if not sandbox_report["hard_boundary"]:
        print("  FAIL-CLOSED NOTICE: " + sandbox_report.get(
            "reason", sandbox_report.get("warning", "hard boundary unavailable")))

    try:
        blocks, used_mock = run("Write a one-line summary note about SAB, checksum it, and list the workspace.")
    except RuntimeError as exc:
        print("\nmodel error: " + str(exc))
        print("No substitute model was used. Set AGENT_ALLOW_MOCK=1 only for an offline demo.")
        return 3
    print("\n[model path] " + ("MOCK (explicit or permitted fallback)" if used_mock else "LIVE Gemini -> " + MODEL))

    decoded = [decode_record(bytes.fromhex(block["stateRcsHex"])) for block in blocks]
    expected_tools = ["write_note", "sha256_note", "list_notes"]
    actual_tools = [record["tool"] for record in decoded]
    postcondition_ok = (
        actual_tools == expected_tools
        and all(record["status"] == "ok" for record in decoded)
    )
    print("[controller postcondition] " + (
        "SATISFIED: required actions completed"
        if postcondition_ok
        else "NOT SATISFIED: model completion claim rejected"
    ))

    src = os.path.join(HERE, "agent_loop_ledger.jsonl")
    write_jsonl(blocks, src)
    ok, _, reason = verify_chain(src)
    print("\nrecorded " + str(len(blocks)) + " clearance records -> " + os.path.basename(src))
    print("self-verify: " + ("OK" if ok else "FAIL") + " -- " + reason)

    # out-of-band anchor: seal the tail somewhere the attacker cannot reach, so a
    # full rewrite-from-genesis or a rollback is caught, not just a byte edit.
    # (forgery_demo.py performs those two attacks and shows this catching them.)
    notary = os.path.join(HERE, "agent_loop_notary.log")
    arec = anchor(src, notary)
    va = verify_with_anchor(src, notary)
    print("anchor: sealed out-of-band len=" + str(arec["len"]) + " tail=" + arec["tail"][:12]
          + ".. -> anchor check " + ("OK" if va["anchor_ok"] else "MISMATCH"))

    # tamper: flip one recorded byte and re-derive the hash IN MEMORY (no temp file)
    if blocks:
        import copy
        bad0 = copy.deepcopy(blocks[0])
        hexs = bad0["stateRcsHex"]
        bad0["stateRcsHex"] = hexs[:-1] + ("0" if hexs[-1] != "0" else "1")
        rcs = bytes.fromhex(bad0["stateRcsHex"])
        recomputed = block_hash(bad0["index"], bad0["timestampMs"], bad0["prevHash"], rcs)
        detected = recomputed != bad0["blockHash"]
        print("tamper test: edited block 0 -> " + ("DETECTED (hash no longer matches)" if detected else "MISSED"))

    print("\ncross-runtime: verify this agent decision trace in C# too ->")
    print("  dotnet run --project xrt_verify -- agent_loop_ledger.jsonl")
    print(line)
    return 0 if (ok and sandbox_report["hard_boundary"] and postcondition_ok) else 2


if __name__ == "__main__":
    raise SystemExit(main())
