#!/usr/bin/env python3
"""
agent_ledger.py — deterministic, replayable, tamper-evident ledger for AI agent actions.

SELF-CONTAINED demo: no external packages, no absolute paths. Anyone can run:

    python agent_ledger.py

Then independently verify the same ledger from a DIFFERENT language:

    dotnet run --project xrt_verify -- agent_ledger.jsonl

The canonical serialization + block-hash here are a vendored copy of the tested
regime_math substrate (kept byte-identical). The point of this demo is that the
proof does not depend on who runs it: two independent implementations re-derive
the same hashes, or they don't. No credentials required.

Stdlib only. Python 3.9+.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from fractions import Fraction

GENESIS = "0" * 64


# --- canonical record serialization (RCS; vendored, byte-identical) ----------
def _enc_bigint(n: int) -> bytes:
    sign = b"\x01" if n < 0 else b"\x00"
    mag = abs(int(n))
    length = (mag.bit_length() + 7) // 8
    body = mag.to_bytes(length, "big") if length else b""
    return sign + length.to_bytes(4, "big") + body


def _enc_rational(num: int, den: int) -> bytes:
    if den < 0:
        num, den = -num, -den
    return bytes([0x01]) + _enc_bigint(num) + _enc_bigint(den)


def _enc_string(s: str) -> bytes:
    b = s.encode("utf-8")
    return bytes([0x05]) + len(b).to_bytes(4, "big") + b


def encode_record(fields: dict) -> bytes:
    """Fields (name -> str | int | Fraction) emitted sorted by name -> canonical bytes."""
    items = sorted(fields.items(), key=lambda kv: kv[0])
    out = bytearray([0x30])
    out += len(items).to_bytes(4, "big")
    for name, val in items:
        nb = name.encode("utf-8")
        out += len(nb).to_bytes(4, "big") + nb
        if isinstance(val, str):
            out += _enc_string(val)
        else:
            fr = Fraction(val)
            out += _enc_rational(fr.numerator, fr.denominator)
    return bytes(out)


def _dec_bigint(b: bytes, i: int):
    sign = b[i]; i += 1
    ln = int.from_bytes(b[i:i + 4], "big"); i += 4
    mag = int.from_bytes(b[i:i + ln], "big") if ln else 0
    i += ln
    return (-mag if sign == 1 else mag), i


def decode_record(rcs: bytes) -> dict:
    """Inverse of encode_record: recover fields from the canonical hashed bytes.
    The tower reads THIS (the payload the block hash commits to), never the
    agent's own convenience fields, so a lying agent cannot mislead the audit."""
    from fractions import Fraction
    assert rcs[0] == 0x30, "not a record"
    i = 1
    count = int.from_bytes(rcs[i:i + 4], "big"); i += 4
    fields = {}
    for _ in range(count):
        nlen = int.from_bytes(rcs[i:i + 4], "big"); i += 4
        name = rcs[i:i + nlen].decode("utf-8"); i += nlen
        tag = rcs[i]; i += 1
        if tag == 0x05:                                   # string
            slen = int.from_bytes(rcs[i:i + 4], "big"); i += 4
            fields[name] = rcs[i:i + slen].decode("utf-8"); i += slen
        elif tag == 0x01:                                 # rational
            num, i = _dec_bigint(rcs, i)
            den, i = _dec_bigint(rcs, i)
            fields[name] = num if den == 1 else Fraction(num, den)
        else:
            raise ValueError("unknown field tag: %d" % tag)
    return fields


def block_hash(index: int, timestamp_ms: int, prev_hash: str, rcs: bytes) -> str:
    h = bytearray()
    h.append(0x20)
    h += index.to_bytes(8, "big")
    h += timestamp_ms.to_bytes(8, "big")
    h += bytes.fromhex(prev_hash)
    h += len(rcs).to_bytes(4, "big")
    h += rcs
    return hashlib.sha256(bytes(h)).hexdigest()


def verify_chain(path: str):
    prev = GENESIS
    with open(path, encoding="utf-8") as handle:
        blocks = [json.loads(line) for line in handle if line.strip()]
    for i, b in enumerate(blocks):
        if b["index"] != i:
            return (False, i, "index mismatch")
        if b["prevHash"] != prev:
            return (False, i, "broken link: prevHash != previous block hash")
        rcs = bytes.fromhex(b["stateRcsHex"])
        if block_hash(b["index"], b["timestampMs"], b["prevHash"], rcs) != b["blockHash"]:
            return (False, i, "hash mismatch: block content was altered")
        prev = b["blockHash"]
    return (True, -1, f"{len(blocks)} blocks intact")


# --- agent action -> ledger --------------------------------------------------
def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def action_record(a: dict) -> dict:
    return {"step": a["step"], "tool": a["tool"], "args": canon(a["args"]),
            "result": canon(a["result"]), "status": a["status"]}


def build_ledger(actions, t0: int = 1_720_000_000_000):
    blocks, prev = [], GENESIS
    for i, a in enumerate(actions):
        payload = encode_record(action_record(a))
        ts = t0 + i * 1000
        h = block_hash(i, ts, prev, payload)
        blocks.append({"index": i, "timestampMs": ts, "prevHash": prev,
                       "stateKind": "agent_action", "tool": a["tool"],
                       "stateRcsHex": payload.hex(), "blockHash": h})
        prev = h
    return blocks


def write_jsonl(blocks, path):
    with open(path, "w", encoding="utf-8") as f:
        for b in blocks:
            f.write(json.dumps(b) + "\n")


AGENT_RUN = [
    {"step": 0, "tool": "search",         "args": {"q": "exact cross-runtime serialization"}, "result": {"hits": 3}, "status": "ok"},
    {"step": 1, "tool": "fetch",          "args": {"url": "https://arxiv.org/abs/2606.11632"}, "result": {"http": 200, "bytes": 48213}, "status": "ok"},
    {"step": 2, "tool": "extract_claims", "args": {"doc": "2606.11632"}, "result": {"claims": 5, "evidence": 4}, "status": "ok"},
    {"step": 3, "tool": "write_file",     "args": {"path": "notes/sab.md"}, "result": {"written": True, "bytes": 1820}, "status": "ok"},
    {"step": 4, "tool": "commit",         "args": {"msg": "add SAB notes"}, "result": {"sha": "a1b2c3d4"}, "status": "ok"},
]

# Fixed expected tail hash — a stranger's run must reproduce this exactly.
EXPECTED_TAIL = "b1ab8a01a00c"


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(here, "agent_ledger.jsonl")
    line = "=" * 70

    print(line)
    print("AGENT ACTION LEDGER  --  deterministic | replayable | tamper-evident")
    print(line)

    blocks = build_ledger(AGENT_RUN)
    write_jsonl(blocks, src)
    print(f"\nRecorded agent run ({len(blocks)} actions):")
    for b in blocks:
        print(f"  [{b['index']}] {b['tool']:<14} block {b['blockHash'][:12]}...")
    tail = blocks[-1]["blockHash"][:12]
    ok, _, reason = verify_chain(src)
    print(f"  chain tail: {tail}   (expected {EXPECTED_TAIL})  "
          f"{'MATCH' if tail == EXPECTED_TAIL else 'DIFFERENT'}")
    print(f"  self-verify: {'OK' if ok else 'FAIL'} -- {reason}")

    print("\n[1] DETERMINISTIC REPLAY")
    replay = build_ledger(AGENT_RUN)
    same = replay[-1]["blockHash"] == blocks[-1]["blockHash"]
    print(f"  re-ran the same {len(AGENT_RUN)} actions -> tail {replay[-1]['blockHash'][:12]}...  "
          f"{'MATCH (byte-identical)' if same else 'MISMATCH'}")
    print("  => a failed agent run can be reproduced exactly, not guessed at.")

    print("\n[2] TAMPER DETECTION")
    tampered = dict(AGENT_RUN[2], result={"claims": 5, "evidence": 3})  # 4 -> 3
    bad = copy.deepcopy(blocks)
    bad[2]["stateRcsHex"] = encode_record(action_record(tampered)).hex()
    bad_path = os.path.join(here, "agent_ledger.tampered.jsonl")
    write_jsonl(bad, bad_path)
    tok, tidx, treason = verify_chain(bad_path)
    print("  attacker rewrote step 2 result:  evidence 4 -> 3")
    print(f"  verify -> {'OK' if tok else 'DETECTED'} at block {tidx}: \"{treason}\"")
    print("  => the recorded action trace cannot be silently edited.")
    os.remove(bad_path)

    print("\n[3] CROSS-RUNTIME (run this to prove it, don't take my word)")
    print("  dotnet run --project xrt_verify -- agent_ledger.jsonl")
    print("  => a C# implementation re-derives every hash above and must agree bit-for-bit.")

    print("\n" + line)
    print("Every agent action is exactly recorded, replayable, and tamper-evident --")
    print("and verifiable by anyone, in any language, without trusting who produced it.")
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
