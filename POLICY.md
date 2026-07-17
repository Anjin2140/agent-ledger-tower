# Policy format — control-tower clearance rules

Policy is data, not executable code. The JSON file can be inspected, diffed,
signed, and independently reimplemented.

## Deterministic evaluation order

1. Evaluate deny rules in file order. The first match denies the request.
2. If no deny matched, evaluate allow rules in file order.
3. If no rule matched, apply the default. The shipped policy is default deny.

Deny-before-allow means an allowed tool name does not override a dangerous path
or secret-bearing argument.

## Rule conditions

A rule matches only when every condition it contains is true. A rule with no
recognized conditions never matches.

| Key | Meaning |
|---|---|
| tool | Exact tool-name match |
| arg_contains | Case-insensitive substring in canonical arguments |
| arg_matches | Regular expression against canonical arguments and string values |
| arg_gt | Numeric field threshold |

## Shipped policy

Version 2 explicitly allows only write_note, sha256_note, and list_notes. It
denies insecure TLS arguments, path traversal or absolute paths, and references
to common secret material. Every unknown tool is denied by default.

## Recorded evidence

Each ledger record contains:

    step, tool, args, decision, rule, result, status, enforcement

The enforcement field identifies whether the action ran in the hard OS boundary,
was never launched because policy denied it, or was blocked because the sandbox
was unavailable. The fleet tower independently checks this field from the hashed
canonical bytes.

## Scope

The policy layer is one part of the boundary. Structural validation and the
worker's real-path jail protect tool arguments; Docker isolates the worker from
the controller, credentials, host filesystem, and network. Regex rules remain
defense in depth, not the sole security mechanism.