# Agent Ledger — Verification Spec (language-agnostic)

This document is enough to write your own verifier in any language with SHA-256.
Nothing here depends on the reference Python/C#/Node code. Independence is the point:
you should not have to trust who produced the ledger — you reproduce the verdict.

## Inputs (public)

1. **Ledger** — a JSON-lines file. One block per line, in order:
   ```
   {"index":0,"timestampMs":1720000000000,"prevHash":"<64 hex>",
    "tool":"...","stateRcsHex":"<hex>","blockHash":"<64 hex>"}
   ```
2. **Notary log** (optional but recommended) — a JSON-lines append-only file kept
   OUT OF BAND (somewhere the ledger's author cannot retroactively edit). Each line:
   ```
   {"anchoredAtMs":<int>,"len":<int>,"tail":"<64 hex>"}
   ```
   Use the LAST line (the most recent seal).

## Constants
- `GENESIS` = 64 ASCII `'0'` characters (the prev-hash of block 0).
- All integers below are **big-endian**.
- `rcs` = the raw bytes of `stateRcsHex` decoded from hex. Treat it as **opaque
  canonical bytes**; you do NOT need to understand its internal structure to verify
  integrity — only to feed it into the block hash.

## Block hash
For each block compute:
```
H = SHA256(
      0x20                      // 1 byte, literal
    | index        as 8 bytes   // big-endian
    | timestampMs  as 8 bytes   // big-endian
    | prevHash     as 32 bytes  // the 64-hex string decoded to raw bytes
    | length(rcs)  as 4 bytes   // big-endian byte count of rcs
    | rcs                       // the opaque bytes
)
```
`H` (lowercase hex) must equal the block's `blockHash`.

## Chain rules
Walk blocks in file order with `prev = GENESIS`:
1. `block.index` must equal its position `i` (0,1,2,…).
2. `block.prevHash` must equal `prev`.
3. recomputed `H` must equal `block.blockHash`.
4. set `prev = block.blockHash` and continue.
If all blocks pass, the chain is **internally consistent**.

## Why the chain alone is not enough
Internal consistency proves only that the file is self-coherent. An attacker who
controls the whole file can **rewrite every block from genesis and recompute every
hash** — the chain will still pass. Dropping the last N blocks also leaves a valid
shorter chain. Detecting those requires the anchor.

## Anchor rules (closes the loophole)
Let `A` = the last record in the notary log. The ledger is authentic only if BOTH:
- `number_of_blocks == A.len`, and
- `your_recomputed_tail == A.tail`  (compare YOUR recomputed final `H`, not the
  file's stored `blockHash`).

- Tail mismatch  → the ledger was **rewritten**.
- Length mismatch → the ledger was **truncated / rolled back** (or extended).

The anchor's trustworthiness equals the out-of-band-ness of where it is stored
(append-only store off-box, external timestamp, public chain, printed hash). The
verifier makes the check; the deployment makes the anchor trustworthy.

## Reference verdicts (from the demo)
- `agent_ledger.py` honest run → chain tail `b1ab8a01a00c…`, 5 blocks.
- Independent verifiers (C#, Node) reproduce the same hashes byte-for-byte, and the
  anchor check rejects both the from-genesis rewrite and the truncation.
