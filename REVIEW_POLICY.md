# Review and Consolidation Policy

**Status:** public package policy
**Applies to:** source, scripts, documentation, tests, and configuration proposed for this repository

## Purpose

This repository is a reference implementation, not a general-purpose operating
system. New work must improve one of its concrete capabilities without creating
another parallel framework. The active product is a local control tower for
source-backed retrieval, exact calculations, governed actions, and independent
verification.

## One canonical implementation

Each capability has one home in this repository:

- policy and authorization: `policy_gate.py` and `default_policy.json`;
- isolation: `sandbox.py`, `sandbox_worker.py`, and `Dockerfile.sandbox`;
- records and verification: `agent_ledger.py`, `agent_notary.py`, `verify.js`, and `xrt_verify/`;
- agent and fleet control: `agent_loop.py`, `fleet_tower.py`, and `operator_console.py`;
- retrieval, chat, and exact math: `memory_index.py`, `chat_console.py`, `response_quality.py`, and `exact_math_tool.py`;
- user interface: `tower_console.py`;
- model transport and evaluation: `gemini_config.py`, the benchmark files, and the review tool.

Do not add a second implementation of an existing capability merely because it
has a different label, prompt, or mythology. Keep experiments outside the
release allowlist until they have a measured use case.

## Required review for every new file

Before a file enters the release allowlist, its review record must state:

1. the concrete problem it removes;
2. its inputs and outputs;
3. its failure modes;
4. the existing component it reuses;
5. the test that proves its stated contract;
6. its status: workable, refine, prototype, rework, or archive;
7. the claim it is not entitled to make.

The file must also have a meaningful regression test when it changes behavior.
`component_review.py` fails closed when a release file lacks a review record or
when two components claim the same file. `release_hygiene.py` checks the
allowlist, manifest, runtime exclusions, legacy terminology, common credential
patterns, and unsafe paths.

## Evidence and claims

The project distinguishes four things:

- **Evidence:** a source excerpt, test result, ledger record, or verifier output.
- **Inference:** a conclusion derived from evidence and labeled as such.
- **Unknown:** information not established by the current evidence.
- **Claim:** a statement that must stay within the tested contract.

Exact rational arithmetic improves calculation reproducibility. It does not
solve hallucination, context loss, factuality, or sycophancy. Retrieval gives
provenance, not truth. A model is an untrusted proposal source; it cannot grant
itself authority by claiming that an action succeeded.

## Execution boundary

Read-only retrieval and exact math do not require Docker. Controlled actions do:
the default path is a deny-first policy, one approved action, a fresh per-run
workspace, and a networkless
bounded worker, a postcondition check, and a tamper-evident ledger record. If
hard Docker mode is unavailable, the proof exits nonzero and the system must not
present a contained-action claim.

## Consolidation workflow

For a proposed change:

1. state the problem in ordinary engineering language;
2. identify the canonical component that should own it;
3. write the review record and smallest useful test;
4. implement the change;
5. run the component and hygiene checks;
6. run the complete hard-gated proof;
7. update the README or specification if the operator contract changed.

Anything that cannot meet this workflow remains an experiment or archive item;
it is not silently promoted into the product.
