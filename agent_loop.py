#!/usr/bin/env python3
"""
agent_loop.py — a REAL agent loop whose every action is recorded into the
deterministic, tamper-evident ledger.

The model is called through Google's Gemini REST API using only the Python
standard library (urllib + ssl + json) — no third-party packages to install,
which sidesteps the litellm/Rust build problem entirely. If a key or network
is absent, it falls back to a deterministic MOCK model so the loop + ledger
still run offline and prove the mechanics.

To run against REAL Gemini (on a machine with network):
    setx GEMINI_API_KEY "...your key..."      (then open a NEW terminal)
    set  AGENT_MODEL=gemini-flash-latest      (optional; whatever model is current)
    python agent_loop.py

The ledger records the ACTIONS, not the model — so the audit trail is identical
whichever model produced it. To use a different provider, replace call_model();
everything downstream (recording, hashing, verification) is provider-agnostic.

Security: TLS certificate verification is ON by default. If your network does
TLS interception and you hit a certificate error, point Python at your corporate
root CA:  set SSL_CERT_FILE=C:\path\to\corp-root.pem
Only as a last, deliberate resort you can set AGENT_INSECURE_TLS=1 to disable
verification — it prints a loud warning and must never be used with a real key
on an untrusted network.

Stdlib only. Python 3.9+.
"""
from __future__ import annotations

import hashlib
import json
import os
import ssl
import urllib.request

# Optional .env support (only if python-dotenv happens to be installed).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from agent_ledger import (encode_record, block_hash, verify_chain, GENESIS,
                          action_record, write_jsonl)
from agent_notary import anchor, verify_with_anchor
from policy_gate import load_policy, evaluate, decision_record


# --- key discovery: prefer the current environment, else read what `setx` stored
def _get_user_env(name: str) -> str:
    """Read a persistent user env var from the Windows registry (what setx writes).
    A value set with `setx` in another window is NOT visible via os.environ in this
    process, so we look it up directly. No-op on non-Windows."""
    try:
        import winreg  # Windows only
    except ImportError:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            return winreg.QueryValueEx(key, name)[0]
    except Exception:
        return ""


if not os.environ.get("GEMINI_API_KEY"):
    _found = _get_user_env("GEMINI_API_KEY")
    if _found:
        os.environ["GEMINI_API_KEY"] = _found

MODEL = os.environ.get("AGENT_MODEL", "gemini-flash-latest")

# CLEARANCE: load the control-tower policy (allow-all if none present).
_POLICY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "default_policy.json")
POLICY = load_policy(_POLICY_PATH) if os.path.exists(_POLICY_PATH) else None

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "agent_work")
os.makedirs(WORK, exist_ok=True)


# --- real, local, sandboxed tools -------------------------------------------
def _safe(name: str) -> str:
    return os.path.basename(str(name))          # no path traversal


def t_write_note(name: str, text: str) -> dict:
    with open(os.path.join(WORK, _safe(name)), "w", encoding="utf-8") as f:
        f.write(text)
    return {"bytes": len(text.encode("utf-8"))}


def t_sha256_note(name: str) -> dict:
    with open(os.path.join(WORK, _safe(name)), "rb") as f:
        return {"sha256": hashlib.sha256(f.read()).hexdigest()}


def t_list_notes() -> dict:
    return {"files": sorted(os.listdir(WORK))}


TOOLS = {"write_note": t_write_note, "sha256_note": t_sha256_note, "list_notes": t_list_notes}

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


def _ssl_context() -> ssl.SSLContext:
    """Secure by default. Honors SSL_CERT_FILE for a corporate root CA.
    AGENT_INSECURE_TLS=1 disables verification (loud warning) — last resort only."""
    ctx = ssl.create_default_context()
    if os.environ.get("AGENT_INSECURE_TLS") == "1":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        print("  !! WARNING: TLS verification DISABLED (AGENT_INSECURE_TLS=1). "
              "Your API key can be intercepted. Do not use on an untrusted network. !!")
    return ctx


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
            fr = {"functionResponse": {
                "name": m.get("name", "tool"),
                "response": {"result": m.get("content", "")}}}
            contents.append({"role": "user", "parts": [fr]})
            continue

        if m["role"] in ("user", "system"):
            parts = []
            if m.get("content"):
                parts.append({"text": m["content"]})
            contents.append({"role": "user", "parts": parts})
            continue

        # assistant turn
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
    """Call Gemini over REST (stdlib only). Fall back to the offline mock on any error."""
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY missing")

        raw_model = MODEL.split("/", 1)[1] if "/" in MODEL else MODEL
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               + raw_model + ":generateContent?key=" + api_key)

        data = json.dumps(_to_gemini(messages, tools)).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        cands = body.get("candidates") or []
        if not cands:
            raise ValueError("no candidates returned: " + str(body))

        raw_msg = {"role": "assistant", "content": None}
        tcs, oai_calls = [], []
        for part in cands[0].get("content", {}).get("parts", []):
            if "text" in part and part["text"]:
                raw_msg["content"] = (raw_msg["content"] or "") + part["text"]
            if "functionCall" in part:
                fc = part["functionCall"]
                tc_id = "call_" + fc["name"]
                args = fc.get("args", {}) or {}
                tcs.append({"id": tc_id, "name": fc["name"], "args": args})
                oai_calls.append({"id": tc_id, "type": "function",
                                  "function": {"name": fc["name"], "arguments": json.dumps(args)}})
        if oai_calls:
            raw_msg["tool_calls"] = oai_calls
        return {"content": raw_msg.get("content"), "tool_calls": tcs, "_raw": raw_msg}

    except Exception as e:
        return {"_mock_reason": type(e).__name__ + ": " + str(e), **mock_model(messages, tools)}


# --- the agent loop, recording every action into the ledger -----------------
def run(task: str, max_turns: int = 8):
    messages = [
        {"role": "system", "content": "You are a careful agent. Use the tools to complete the task, then stop."},
        {"role": "user", "content": task},
    ]
    blocks, prev, step, t0 = [], GENESIS, 0, 1_720_000_000_000
    used_mock = None

    for _ in range(max_turns):
        out = call_model(messages, TOOL_SCHEMA)
        if used_mock is None:
            used_mock = "_mock_reason" in out
        if not out["tool_calls"]:
            print("  [model] final: " + (out.get("content") or "").strip()[:80])
            break
        # thread the assistant turn (real functionCalls preserved for the next request)
        messages.append(out.get("_raw") or {"role": "assistant", "content": None,
            "tool_calls": [{"id": tc["id"], "type": "function",
                            "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}}
                           for tc in out["tool_calls"]]})
        for tc in out["tool_calls"]:
            # CLEARANCE: the tower decides BEFORE the action runs.
            if POLICY is None:
                decision, rule, why = "ALLOW", "no_policy", "no policy loaded"
            else:
                decision, rule, why = evaluate(POLICY, tc["name"], tc["args"])
            if decision == "DENY":
                result, status = {"blocked": True, "reason": why}, "denied"
            else:
                try:
                    result = TOOLS[tc["name"]](**tc["args"])
                    status = "ok"
                except Exception as e:
                    result, status = {"error": str(e)}, "error"
            # RECORD the decision + outcome into the tamper-evident ledger
            payload = encode_record(decision_record(step, tc["name"], tc["args"],
                                                    decision, rule, result, status))
            ts = t0 + step * 1000
            h = block_hash(step, ts, prev, payload)
            blocks.append({"index": step, "timestampMs": ts, "prevHash": prev,
                           "stateKind": "gate_decision", "tool": tc["name"],
                           "stateRcsHex": payload.hex(), "blockHash": h})
            prev = h
            print("  [" + str(step) + "] POLICY " + decision + " (" + rule + ") "
                  + tc["name"] + " -> " + json.dumps(result)[:40] + "  block " + h[:12] + "...")
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

    blocks, used_mock = run("Write a one-line summary note about SAB, checksum it, and list the workspace.")
    print("\n[model path] " + ("MOCK (offline: no key/network here)" if used_mock else "LIVE Gemini -> " + MODEL))

    src = os.path.join(HERE, "agent_loop_ledger.jsonl")
    write_jsonl(blocks, src)
    ok, _, reason = verify_chain(src)
    print("\nrecorded " + str(len(blocks)) + " real tool actions -> " + os.path.basename(src))
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

    print("\ncross-runtime: verify this real-agent trace in C# too ->")
    print("  dotnet run --project xrt_verify -- agent_loop_ledger.jsonl")
    print(line)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
