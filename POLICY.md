# Policy format — the control tower's clearance rules

Policy is **data, not code**: a JSON file the tower loads to decide whether each
proposed agent action may run. It can be inspected, diffed, signed, and
reimplemented in any language. Evaluation is deterministic — the first matching
`deny` rule wins; otherwise the `default` applies.

## Shape
```json
{
  "version": 1,
  "default": "allow",            // "allow" or "deny"
  "rules": [
    {"id": "no_insecure_tls", "effect": "deny",
     "when": {"arg_matches": "(?i)verify\\W{0,3}false|cert_none|--insecure"},
     "reason": "disabling TLS verification is forbidden"}
  ]
}
```

## Rule `when` conditions
A rule matches only if **every** condition present holds. A rule with none of
these keys never matches (no accidental catch-all).

| key            | meaning                                                            |
|----------------|-------------------------------------------------------------------|
| `tool`         | exact tool-name match                                             |
| `arg_contains` | case-insensitive substring anywhere in the arguments             |
| `arg_matches`  | regex, tested against the canonical args blob AND each string value |
| `arg_gt`       | `{"field": <name>, "limit": <number>}` — numeric threshold        |

## Default rules shipped (`default_policy.json`)
- **no_insecure_tls** — blocks `verify=false`, `CERT_NONE`, `--insecure`, disabled-warnings.
- **sandbox_only** — blocks `..` traversal and absolute paths (`C:\…`, `/…`).
- **no_secret_exfil** — blocks references to private keys, mnemonics, seed phrases.
- **spend_cap** — blocks `spend` actions over the numeric limit.

## What gets recorded
Every decision is written to the ledger as a canonical, hashable record:
```
step, tool, args, decision (ALLOW|DENY), rule, result, status
```
Because it lands in the hash-chained, anchored ledger, the tower's decisions —
including refusals — are tamper-evident, replayable, and verifiable in any
runtime (see SPEC.md; the Node and C# verifiers confirm gate ledgers unchanged,
since they hash the record bytes without needing to parse them).

## Honest scope
These default patterns are **illustrative guards**, not a hardened security
policy. Regexes can be evaded; a production tower would combine structural checks
(typed argument schemas, real path canonicalization, capability allow-lists) with
these. The contribution here is the *architecture*: policy as data, deterministic
clearance before execution, and every decision committed to a verifiable record.
