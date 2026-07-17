# Component Review and Boundaries

This file is the plain-language review for the standalone package. It separates
working code from claims that would exceed the evidence.

## Product statement

This is a local reference implementation of a **verifiable control tower for
AI-proposed actions**. It provides source-backed chat, exact rational math when
needed, a deterministic policy gate, a confined worker, and a tamper-evident
record that C# and Node can independently verify.

It is not a new processor, an IEEE-754 replacement, a factuality oracle, or a
production-grade security boundary for hostile multi-user systems.

## Reviewed components

| Files | Purpose | Status | Evidence | Boundary / next refinement |
|---|---|---|---|---|
| `agent_ledger.py`, `agent_notary.py`, `SPEC.md`, `verify.js`, `xrt_verify/` | Canonical action records, hash-chain, anchor comparison, independent verification | Retain and refine | Python writer plus C# and Node re-derive the same test ledger | An anchor beside the ledger is only a demonstration. Deploy an independent anchor before making stronger tamper-resistance claims. |
| `policy_gate.py`, `default_policy.json`, `policy_gate_demo.py` | Default-deny tool authorization | Retain and refine | Deterministic corpus and policy tests | The supplied policy is a small example, not a complete enterprise policy language. |
| `sandbox.py`, `sandbox_worker.py`, `Dockerfile.sandbox`, `SANDBOX.md` | One networkless, bounded worker per approved action | Primary prototype | Eight hostile boundary checks: path escape, unknown tool, child process, network, oversize write, CPU limit, and host-file protection | Docker reduces capability; it does not secure an unpatched host or replace production isolation review. |
| `agent_loop.py`, `fleet_tower.py`, `operator_console.py` | Controlled agent demo, cross-agent audit, and fleet controls | Primary prototype | Policy, postcondition, ledger, anchor, bounded action timeout, rogue-fleet, and fresh-run-workspace scenarios | The demo agent is intentionally small. Add real tools only one at a time with explicit policy, postcondition, and threat model. |
| `tower_console.py`, `start_tower.ps1`, `test_tower_console.py` | One local UI for chat, math, fleet visibility, operator controls, explicit release review, and opt-in prompt-free Gemini readiness checks | Retain and refine | HTTP integration test covers page, status, token rejection, exact math, fleet action, release-review route, and model-preflight route | Localhost UI only. It does not authenticate multiple users or expose a remote service. |
| `memory_index.py`, `chat_console.py`, `response_quality.py`, `exact_math_tool.py`, `start_chat.ps1` | Deterministic selected-source retrieval, local digest-addressed evidence snapshots, citations, read-only chat, and exact rational expressions | Retain and refine | Retrieval tie-break, packet snapshot/ledger, citation, exactness, false-action-claim, and input-rejection tests | A snapshot preserves selected source context, not the user question or model output. It can contain private excerpts, stays local, and is not encrypted by this package; it does not make a source true or a model factual. |
| `gemini_config.py`, `gemini_preflight.py`, `windows_native_http.ps1`, `SETUP_GEMINI.md` | Private key discovery, stable model selection, and safe connectivity check | Retain and refine | 10 configuration tests; prompt-free model-list preflight; six successful Gemini 3.1 Flash-Lite benchmark responses with digest-bound human review; live agent loop completed after preserving Gemini 3 function-call signatures and IDs | The transport fallback is narrowly allowlisted and certificate-verifying. The live sample is exploratory, not a broad model-quality claim. |
| `evaluation_cases.json`, `evaluation_suite.py`, `live_benchmark_cases.json`, `live_model_benchmark.py`, `review_live_benchmark.py` | Deterministic controller tests and separately human-scored live-model protocol | Retain and expand | 24 deterministic cases; live workflow refuses to score failed requests as model behavior | A structural corpus is not an intelligence benchmark. Live results need successful calls and human review. |
| `run_all.ps1`, `run_all.sh`, `setup_sandbox.*`, `export_standalone.ps1`, `release_hygiene.py`, `active_tree_review.py`, `.github/workflows/verify.yml` | Reproducible local proof, clean export, active-tree admission, release hygiene, and planned hosted CI | Retain | Full local proof exits nonzero if hard Docker mode is unavailable; active-tree, manifest, language, credential-pattern, and runtime-ignore checks cover exported source | Hosted GitHub Actions has not run yet. Pattern checks are not a full secret scan or security review. |
| `README.md`, `VERIFIABLE_AI_WORKFLOWS.md`, `REVIEW_POLICY.md`, `PUBLISHING.md`, `POLICY.md`, `COMPONENTS.md`, `LICENSE` | First-use instructions, architecture paper, file-admission policy, safe publication handoff, scope, review boundaries, and licensing | Retain | Reviewed alongside source and included in the manifest | Keep statements aligned with reproducible tests; the paper, policy, and publishing handoff do not claim production security or model factuality. |
| `component_review.py`, `component_review_registry.json`, `release_files.json`, `active_tree_exclusions.json`, `test_active_tree_review.py` | Fail-closed file-review contract, active-tree admission, and one clean-export allowlist | Retain and refine | Validators refuse missing review records or unallowlisted non-runtime files; focused tests cover malformed and hostile admission cases | They enforce review coverage, not code correctness or production security. |

## New-file review protocol

Every new module must answer these questions before it joins the package:

1. What concrete problem does it remove?
2. What are its inputs, outputs, and failure modes?
3. Which existing component should it reuse instead of duplicating?
4. What test proves its stated contract?
5. What claim is it **not** entitled to make?

If those answers are missing, keep the file outside the release as an
experiment. If the module only changes wording, scores, or mythology without a
testable capability, discard it.

The rule is executable: run `python active_tree_review.py` and
`python component_review.py`. The same `release_files.json` allowlist drives
active-tree admission, clean export, and review coverage. To admit a new file,
add it to that allowlist, assign it to exactly one reviewed component, add the
smallest meaningful test, then run the full proof. A file that is only an
experiment should remain outside the allowlist.

## Generated state is not source

Ledgers, anchors, SQLite databases, `fleet/`, `agent_work/`, logs, caches,
credentials, and raw benchmark responses are local runtime artifacts. They are
ignored by Git and excluded from the export. They can be evidence for a specific
run, but they are not reusable source code.

## Explicit non-goals

- Exact rational arithmetic does not cure hallucination, context selection, or
  sycophancy.
- A model instruction does not create enforcement; policy and isolation do.
- A hash chain is not tamper-proof without an independent anchor.
- A local UI is not multi-user access control.
- A passing mock test is not evidence of live-model quality.
