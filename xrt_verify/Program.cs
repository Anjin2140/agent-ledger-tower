// xrt_verify — independent C# verifier for the agent action ledger.
//
// A SEPARATE language implementation of the same block-hash spec the Python side
// uses. It re-derives every block hash from the raw JSONL and checks the chain.
// If Python wrote the ledger and C# agrees on every hash, the audit trail is
// runtime-agnostic — the whole point.
//
// Optionally it also re-checks the OUT-OF-BAND ANCHOR: pass a notary-log path as a
// second argument and C# will independently confirm that its recomputed tail and
// block count match the sealed anchor. A bare hash-chain can be rewritten from
// genesis and still self-verify; the anchor is what catches that.
//
// Block-hash layout (must match agent_ledger.py / LedgerChain.cs), big-endian:
//   0x20 | index(8) | timestampMs(8) | prevHash(32 raw) | len(rcs)(4) | rcs
//
// Usage:
//   dotnet run --project xrt_verify -- <ledger.jsonl> [notary.log]

using System;
using System.IO;
using System.Security.Cryptography;
using System.Text.Json;

internal static class Program
{
    private static byte[] U64(long v)
    {
        var b = new byte[8];
        for (int i = 7; i >= 0; i--) { b[i] = (byte)(v & 0xFF); v >>= 8; }
        return b;
    }

    private static byte[] U32(uint v) =>
        new[] { (byte)(v >> 24), (byte)(v >> 16), (byte)(v >> 8), (byte)v };

    private static string BlockHash(long index, long ts, string prevHex, byte[] rcs)
    {
        using var ms = new MemoryStream();
        ms.WriteByte(0x20);
        ms.Write(U64(index));
        ms.Write(U64(ts));
        ms.Write(Convert.FromHexString(prevHex));
        ms.Write(U32((uint)rcs.Length));
        ms.Write(rcs);
        using var sha = SHA256.Create();
        return Convert.ToHexString(sha.ComputeHash(ms.ToArray())).ToLowerInvariant();
    }

    private static int Main(string[] args)
    {
        string path = args.Length > 0 ? args[0] : "agent_ledger.jsonl";
        string notaryPath = args.Length > 1 ? args[1] : null;
        if (!File.Exists(path)) { Console.Error.WriteLine($"not found: {path}"); return 2; }

        string genesis = new string('0', 64);
        string prev = genesis;
        int count = 0, fails = 0;
        string lastRecomputed = genesis;

        Console.WriteLine($"C# cross-runtime verify: {Path.GetFileName(path)}");
        Console.WriteLine(new string('-', 62));

        foreach (var line in File.ReadAllLines(path))
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            using var doc = JsonDocument.Parse(line);
            var e = doc.RootElement;
            long index = e.GetProperty("index").GetInt64();
            long ts = e.GetProperty("timestampMs").GetInt64();
            string prevHash = e.GetProperty("prevHash").GetString();
            string rcsHex = e.GetProperty("stateRcsHex").GetString();
            string logged = e.GetProperty("blockHash").GetString();
            string tool = e.TryGetProperty("tool", out var t) ? t.GetString() : "";

            byte[] rcs = Convert.FromHexString(rcsHex);
            string recomputed = BlockHash(index, ts, prevHash, rcs);
            bool linkOk = prevHash == prev;
            bool hashOk = recomputed == logged;
            if (!(linkOk && hashOk)) fails++;

            Console.WriteLine($"  [{(linkOk && hashOk ? "PASS" : "FAIL")}] block {index} ({tool}) " +
                              $"recomputed=={logged[..12]}...  link_ok={linkOk}");
            prev = logged;
            lastRecomputed = recomputed;
            count++;
        }

        Console.WriteLine(new string('-', 62));
        Console.WriteLine(fails == 0
            ? $"CHAIN: {count} blocks verified in C# — matches Python bit-for-bit"
            : $"CHAIN: {fails} FAILURE(S) — chain does not verify");

        // --- out-of-band anchor check (optional) ---------------------------------
        int anchorFail = 0;
        if (notaryPath != null)
        {
            Console.WriteLine(new string('-', 62));
            if (!File.Exists(notaryPath))
            {
                Console.Error.WriteLine($"ANCHOR: notary not found: {notaryPath}");
                anchorFail = 1;
            }
            else
            {
                string lastRec = null;
                foreach (var line in File.ReadAllLines(notaryPath))
                    if (!string.IsNullOrWhiteSpace(line)) lastRec = line;

                if (lastRec == null) { Console.Error.WriteLine("ANCHOR: no records"); anchorFail = 1; }
                else
                {
                    using var adoc = JsonDocument.Parse(lastRec);
                    var a = adoc.RootElement;
                    long anchoredLen = a.GetProperty("len").GetInt64();
                    string anchoredTail = a.GetProperty("tail").GetString();

                    bool lenOk = count == anchoredLen;
                    bool tailOk = lastRecomputed == anchoredTail;
                    anchorFail = (lenOk && tailOk) ? 0 : 1;

                    Console.WriteLine($"ANCHOR: recomputed tail {lastRecomputed[..12]}.. len {count}");
                    Console.WriteLine($"        sealed     tail {anchoredTail[..12]}.. len {anchoredLen}");
                    Console.WriteLine(anchorFail == 0
                        ? "ANCHOR: matches sealed anchor — rewrite/rollback would be caught here"
                        : (!lenOk ? "ANCHOR: LENGTH MISMATCH — truncation/rollback detected"
                                  : "ANCHOR: TAIL MISMATCH — ledger was rewritten"));
                }
            }
        }

        return (fails == 0 && anchorFail == 0) ? 0 : 1;
    }
}
