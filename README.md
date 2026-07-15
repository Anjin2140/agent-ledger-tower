# Agent Ledger Tower

**A verifiable, tamper-evident control tower for AI agent fleets.**

The industry raced to agent *capability* and skipped *accountability*. Fleets of
autonomous agents now take real actions — writing files, calling APIs, moving
money — with little independent record of what they did, no authority to stop an
unsafe action *before* it runs, and no way to prove the audit trail wasn't edited
afterward. This is a small, dependency-light reference implementation of that
missing layer.

Three things a control tower must do — see every action, clear or deny it, and
keep a trustworthy record — built on one property that makes the whole thing
credible: **you don't have to trust the author. You run the verifier.**

- **Verifiable audit root** — every action is a block in a deterministic,
  hash-linked ledger, sealed by an out-of-band anchor. Two independent languages
  (C#, Node) re-derive the same hashes from a public spec, so the trail is
  *author-independent*.
- **Clearance authority** — a policy gate evaluates every proposed action and can
  **deny it before it executes**; the decision (and the rule that fired) is
  recorded in the same tamper-evident ledger. Denials are auditable too.
- **Fleet oversight** — one tower audits many agents and does *not* trust each
  agent's own gate: it re-adjudicates every recorded action from the hashed bytes,
  catching both **tampering** and **misbehavior**.
- **Operator console** — a live localhost web view of the fleet with a real
  **kill switch** the agents honor, re-verified from the ledger on every refresh.

Everything here is standard-library only (Python 3.9+, plus the .NET 8 SDK and
Node.js for the independent verifiers). Nothing to `pip install`.

---

## Quickstart — run the whole thing

```bash
# Windows PowerShell
powershell -ExecutionPolicy Bypass -File run_all.ps1

# macOS / Linux
./run_all.sh
```

This records a gated agent run, demonstrates the clearance gate blocking hostile
actions, performs two forgery attacks and catches them, then has **C# and Node
independently re-derive** the same ledger. Three green lines = one writer, three
runtimes, same hashes.

## Verify it yourself (don't trust — run)

```bash
python agent_ledger.py                                   # write + replay + tamper-detect
dotnet run --project xrt_verify -- agent_ledger.jsonl    # C# re-derives every hash
node verify.js agent_ledger.jsonl                        # Node re-derives every hash
```

If the Python tail hash equals `b1ab8a01a00c` and both verifiers agree, the ledger
verified across three runtimes on *your* machine. The full byte-layout is in
[SPEC.md](SPEC.md) — enough to write your own verifier in any language with SHA-256.

## The pieces

| Capability          | Run it                              | Source |
|---------------------|-------------------------------------|--------|
| Audit root          | `python agent_ledger.py`            | `agent_ledger.py`, `agent_notary.py` |
| Forgery resistance  | `python forgery_demo.py`            | `agent_notary.py` |
| Clearance gate      | `python policy_gate_demo.py`        | `policy_gate.py`, `default_policy.json` |
| Live agent loop     | `python agent_loop.py`              | `agent_loop.py` (see [SETUP_GEMINI.md](SETUP_GEMINI.md)) |
| Fleet oversight     | `python fleet_tower.py`             | `fleet_tower.py` |
| Operator console    | `python operator_console.py`        | `operator_console.py` → http://127.0.0.1:8765 |
| Independent verify  | C# `xrt_verify/`, Node `verify.js`  | + [SPEC.md](SPEC.md) |

## How it works

Each block commits, under SHA-256, to a fixed big-endian byte layout:
`0x20 | index(8) | timestampMs(8) | prevHash(32) | len(rcs)(4) | rcs`. Blocks are
hash-linked into a chain; the chain proves internal consistency. Because a chain
alone can be rewritten from genesis (recompute every hash) or truncated, an
**out-of-band anchor** seals `(length, tail-hash)` where an attacker can't reach
it — catching exactly those two attacks. The **policy gate** ([POLICY.md](POLICY.md))
adjudicates actions before they run and records each decision as a block. The
**tower** re-verifies every agent and re-adjudicates their recorded actions from
the authoritative decoded bytes, so a rogue agent that bypassed its own gate is
still caught.

## Honest scope

This is a **reference implementation and prototype**, not a hardened product.

- The block hash is plain SHA-256 over a documented canonical layout — not a novel
  primitive, a *verifiable* one. That is the point.
- The anchor's strength equals the out-of-band-ness of where it is stored (an
  append-only store off-box, an external timestamp, a public chain, a printed
  hash) — no more. The code makes the check; the deployment makes the anchor
  trustworthy.
- The default policy rules are **illustrative guards**, not a complete security
  policy. A production tower would pair them with typed argument schemas, real
  path canonicalization, and capability allow-lists.

## Credit

The sample content references the Sovereign Assurance Boundary (SAB), an external
published architecture (He & Yu, 2026); it is cited, not claimed. This project is
an independent implementation of a general accountability layer for agent fleets.

## License

Apache-2.0 — see [LICENSE](LICENSE).
