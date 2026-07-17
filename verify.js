#!/usr/bin/env node
/*
 * verify.js — a SECOND, INDEPENDENT verifier for the agent action ledger.
 *
 * Deliberately NOT attached to the ledger's stack:
 *   - different runtime (Node.js, not Python or C#)
 *   - shares no code with the writer — Node built-ins only (crypto, fs)
 *   - reads only the PUBLIC inputs a stranger would be handed:
 *       the ledger .jsonl and (optionally) the out-of-band notary .log
 *   - reproduces the verdict purely from the documented spec (SPEC.md)
 *
 * If this agrees with the Python writer and the C# verifier on the same file,
 * the audit trail does not depend on who wrote the tooling. That is the point.
 *
 * Usage:  node verify.js <ledger.jsonl> [notary.log]
 * Exit:   0 = chain (and anchor, if given) verified; 1 = forgery; 2 = usage.
 */
'use strict';
const fs = require('fs');
const crypto = require('crypto');

const GENESIS = '0'.repeat(64);

// 8-byte big-endian of a (possibly large) integer, via BigInt.
function u64(n) {
  const b = Buffer.alloc(8);
  let v = BigInt(n);
  for (let i = 7; i >= 0; i--) { b[i] = Number(v & 0xffn); v >>= 8n; }
  return b;
}
// 4-byte big-endian.
function u32(n) { const b = Buffer.alloc(4); b.writeUInt32BE(n >>> 0, 0); return b; }

// Block hash spec (SPEC.md):
//   SHA256( 0x20 | index(8 BE) | timestampMs(8 BE) | prevHash(32 raw) | len(rcs)(4 BE) | rcs )
function blockHash(index, ts, prevHex, rcs) {
  const h = crypto.createHash('sha256');
  h.update(Buffer.from([0x20]));
  h.update(u64(index));
  h.update(u64(ts));
  h.update(Buffer.from(prevHex, 'hex'));
  h.update(u32(rcs.length));
  h.update(rcs);
  return h.digest('hex');
}

function readJsonl(p) {
  return fs.readFileSync(p, 'utf8').split('\n').filter(l => l.trim()).map(l => JSON.parse(l));
}

function main() {
  const [ledgerPath, notaryPath] = process.argv.slice(2);
  if (!ledgerPath) { console.error('usage: node verify.js <ledger.jsonl> [notary.log]'); process.exit(2); }

  const blocks = readJsonl(ledgerPath);
  let prev = GENESIS, fails = 0, lastRecomputed = GENESIS;

  console.log(`independent Node verify: ${ledgerPath.split(/[\\/]/).pop()}`);
  console.log('-'.repeat(62));
  for (let i = 0; i < blocks.length; i++) {
    const b = blocks[i];
    const rcs = Buffer.from(b.stateRcsHex, 'hex');          // rcs treated as opaque canonical bytes
    const recomputed = blockHash(b.index, b.timestampMs, b.prevHash, rcs);
    const indexOk = b.index === i;
    const linkOk = b.prevHash === prev;
    const hashOk = recomputed === b.blockHash;
    if (!(indexOk && linkOk && hashOk)) fails++;
    console.log(`  [${(indexOk && linkOk && hashOk) ? 'PASS' : 'FAIL'}] block ${b.index} (${b.tool || ''}) ` +
                `recomputed==${b.blockHash.slice(0, 12)}...  link_ok=${linkOk}`);
    prev = b.blockHash;
    lastRecomputed = recomputed;
  }
  console.log('-'.repeat(62));
  console.log(fails === 0
    ? `CHAIN: ${blocks.length} blocks verified in Node -- independent of the writing stack`
    : `CHAIN: ${fails} FAILURE(S) -- chain does not verify`);

  let anchorFail = 0;
  if (notaryPath) {
    console.log('-'.repeat(62));
    const recs = readJsonl(notaryPath);
    const a = recs[recs.length - 1];                        // latest out-of-band anchor
    const lenOk = blocks.length === a.len;
    const tailOk = lastRecomputed === a.tail;               // compare OUR recomputed tail
    anchorFail = (lenOk && tailOk) ? 0 : 1;
    console.log(`ANCHOR: recomputed tail ${lastRecomputed.slice(0, 12)}.. len ${blocks.length}`);
    console.log(`        sealed     tail ${String(a.tail).slice(0, 12)}.. len ${a.len}`);
    console.log(anchorFail === 0
      ? 'ANCHOR: matches sealed anchor -- a rewrite or rollback would fail here'
      : (!lenOk ? 'ANCHOR: LENGTH MISMATCH -- truncation/rollback detected'
                : 'ANCHOR: TAIL MISMATCH -- ledger was rewritten from genesis'));
  }
  process.exit((fails === 0 && anchorFail === 0) ? 0 : 1);
}
main();
