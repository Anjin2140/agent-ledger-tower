# Building a Verifiable AI Workbench

**Author:** Christopher E. Adams
**Status:** working architecture paper
**Date:** 2026-07-16

## Abstract

This project began with two correct instincts expressed through a large amount of experimental language:

1. numerical calculations should be reproducible when their inputs are reproducible; and
2. an AI system should not be trusted merely because it says it remembered, reasoned, or completed something.

Those concerns lead to a practical engineering goal, not a claim of a new computer architecture or a self-aware model:

> Build a local workbench where source material is retrievable and cited, exact arithmetic is available when required, and AI-proposed actions are checked, contained, recorded, and independently verifiable.

The system does not eliminate hallucinations, make a model “remember” by itself, or make a local ledger unforgeable. It makes failure visible and limits what an untrusted model can do.

The companion [Review and Consolidation Policy](REVIEW_POLICY.md)
defines the canonical homes, archive boundary, and admission checklist for new
files. This paper describes the system; that policy controls what is allowed to
change it.

## 1. The problem, stated precisely

### 1.1 Numerical drift

IEEE-754 floating point is useful and fast. It rounds many decimal values because they cannot be represented exactly in binary. For finance, deterministic serialization, scientific reproduction, or audit logic, a rational or fixed-point representation can be the appropriate tool.

Exact arithmetic solves **calculation reproducibility**. It does not solve natural language ambiguity, model hallucinations, memory decay, security, or truth.

### 1.2 Context loss and model drift

Language models have no durable, self-validating memory. They operate from the text selected for the current request. A system can fail because it retrieves the wrong material, overlooks a qualification, relies on stale information, or lets a model make an action outside its authority.

The practical answer is not to write stronger prompts. It is to provide:

- source selection with hashes and citations;
- explicit distinction between evidence, inference, and unknown;
- deterministic policy checks;
- tool isolation;
- postcondition checks; and
- an audit trail another implementation can verify.

### 1.3 Sycophancy

A model may phrase confidence as agreement. It may mirror a user's framing even when the evidence is weak. This is a presentation and evaluation problem, not a numerical one.

The workbench addresses it by requiring sources for factual claims, by treating model text as untrusted, and by recording whether the system actually performed the actions it describes.

## 2. The working architecture

```text
                         User
                          |
                 Unified local tower UI
                 /        |         \
        source retrieval  exact math  read-only model response
              |              |                 |
         cited excerpts   exact result    labelled “unverified”
                          |
                 no direct tool access
                          |
             separate controlled-agent workflow
                          |
        deterministic policy -> OS sandbox -> postcondition
                          |
           hash-linked ledger -> external anchor -> verifiers
```

Each layer has one job.

| Layer | Job | What it does not do |
|---|---|---|
| Memory index | Find selected source excerpts with hashes and line ranges | Decide whether a source is true |
| Exact math | Calculate rational expressions without rounding drift | Judge language-model claims |
| Model | Propose text or a plan | Directly execute tools or certify its own claims |
| Response-quality audit | Flag missing Evidence/Inference/Unknown sections, unused supplied citations, and impossible read-only action claims | Establish factual truth |
| Policy gate | Decide allow, deny, or escalate based on rules | Infer intent from poetry |
| Sandbox | Constrain an approved tool action | Prove an unpatched host is invulnerable |
| Ledger and anchor | Detect changes, replay loss, and inconsistencies | Make an on-box log tamper-proof |
| Independent verifiers | Recompute the record in another runtime | Decide whether the action was wise |

## 3. What exists today

The current working set has four real foundations.

### Exact arithmetic

- Python exact rational package: 23 property tests and a 120,000-case quick fuzz run against Python's exact `Fraction` ground truth.
- C# independent kernel: rational arithmetic, Hahn-series examples, canonical serialization, ledger, and anchor harnesses.
- Fixed-point reference: checked overflow, floor division, canonical fingerprints, and culture-independent formatting.

Use exact arithmetic only where the problem demands repeatable numerical results.

### Control tower

The local control-tower prototype currently has:

- a default-deny policy gate;
- one disposable Docker worker per approved action;
- no worker network, no inherited model API key, a read-only root filesystem, capability drop, a single-process limit, and bounded resources;
- hard mode fails closed: if the Docker boundary is unavailable, the proof exits nonzero and records no contained-action claim;
- an append-only action ledger;
- an external anchor check for rewrite and rollback detection;
- independent C# and Node verifiers; and
- a fleet audit that identifies a tampered agent record and an unmediated action.

### Provenance-first memory

The local SQLite full-text index stores selected text sources as chunks with:

- source path;
- SHA-256 hash;
- line range; and
- search score with a stable tie-break order.

It excludes likely secret filenames by default and never indexes the entire machine automatically.

For a model-assisted answer, the controller performs one search, selects one
bounded evidence packet from those exact hits, and computes a SHA-256 digest of
that packet. The answer's citations are drawn from the same packet; the action
ledger records its digest and source count, not the raw prompt or source text.
Before a model request, the packet itself is saved as a Git-ignored local
snapshot keyed by that digest. The snapshot contains the selected source
context, not the user question or model output; if it cannot be saved, the model
request is withheld. It is not encrypted by this package, so sensitive snapshots
still rely on the operator's local account and disk protections. This makes
context selection inspectable and recoverable without turning private working
material into ledger data.

### Local evidence chat

The local chat interface supports:

- `/search` for cited excerpts;
- `/math` for exact-rational calculations;
- `/status` and `/verify` for system visibility; and
- optional read-only Gemini answers when a key is configured and secure model
  connectivity is available.

The chat interface does not execute tools. Its optional model response is checked for a reviewable Evidence/Inference/Unknown structure, use of supplied citations, and impossible action claims. That check flags weak output; it does not establish factual truth. Controlled execution remains separate.

### Unified local tower

The normal operator path is now one local page rather than separate chat and
fleet processes. `start_tower.ps1` launches evidence chat, exact math, fleet
verification, and token-protected operator controls on `127.0.0.1:8767`.
Opening the page does not launch a fleet; that remains an explicit operator
decision. The page has an HTTP integration test for status, token rejection,
exact math, and an approved fleet action.

### Release review discipline

The standalone package has one explicit allowlist of 67 release files. Every
allowlisted file is assigned to exactly one component review record stating its
purpose, inputs, outputs, failure modes, reuse path, test evidence, and an
explicit non-claim. The release validator fails if a new file lacks that record,
if two components claim the same file, or if a required review field is absent.
This is a review-coverage guard, not a substitute for security review or proof
that every implementation decision is correct.

## 4. Standard instructions for any model

The following instruction format is more useful than mythic or self-referential rules because it makes the expected evidence visible.

```text
You are a read-only reasoning component.

For every substantive answer:
1. Separate Evidence, Inference, and Unknown.
2. Cite the provided source identifiers for every factual statement; do not
   invent a citation or imply access to material outside the supplied packet.
3. Do not claim that a file, tool, or system action occurred unless the caller supplies a verified execution record.
4. If the sources do not support a claim, say “Unknown” rather than filling the gap.
5. For an action request, return a structured proposal:
   objective, proposed tool, arguments, expected postcondition, reversibility, and risks.
6. You may propose; you have no authority to execute.
7. Do not praise or validate a belief merely because the user states it. Evaluate the supplied evidence and name the uncertainty.
```

The controller—not the model—enforces the authority boundary.

## 5. Operational workflows

### Workflow A: research and writing

1. Select a small source folder explicitly. The default tower launch uses
   curated documentation and notes; use `start_tower.ps1 -IncludeWorkingSet`
   when code from the retained math implementations is needed.
2. Refresh the index. Generated directories, build output, virtual environments,
   local ledgers, and likely secret filenames are excluded by the indexer.
3. Search for a topic in the local chat.
4. Read the cited excerpts, not just a summary.
5. Ask the model for a read-only answer using the selected evidence packet.
6. Mark claims in the output as evidence, inference, or unknown.
7. Store final decisions as a short authored note with sources.

Success criterion: another person can find the source passages that supported a
claim, confirm the packet digest that was supplied to the model, and inspect the
matching private packet snapshot when it has been retained.

Use the unified page for this workflow first. Standalone chat remains available
only when a fleet view is unnecessary.

### Workflow B: exact calculation

1. Use `/math` for a calculation requiring exact decimal/rational semantics.
2. Save the fraction result and source inputs with the decision.
3. Use standard floating point only where bounded rounding error is acceptable and documented.

Success criterion: the result can be recomputed from the textual expression.

### Workflow C: controlled agent action

1. The user describes the goal.
2. A model proposes a structured action; it does not run it.
3. The policy gate allows, denies, or asks for an operator decision.
4. An allowed action runs in a fresh sandbox.
5. The controller checks a postcondition.
6. The system records the decision, result, and enforcement tier in the ledger.
7. An anchor and independent verifier check the history.

Success criterion: the model cannot convert a textual claim into a privileged host action without crossing every listed control.

### Workflow D: release review

1. Run the one-command proof; treat a nonzero exit as a failed release check, including when Docker is unavailable.
2. Run the release-review validator; a missing review record rejects the package.
3. Run the Python math properties and fuzz smoke test.
4. Run the C# exact-math harness.
5. Record the resulting versions, hashes, and known limitations.
6. Publish only source, tests, and generated evidence—never local credentials, wallet files, archive dumps, or model output treated as fact.

Success criterion: a stranger can reproduce the advertised checks on a clean machine.

## 6. Realistic goals

### Achievable in the next 30 days

- Commit and publish the staged clean standalone export, then obtain its first hosted CI run before claiming hosted coverage.
- Preserve the verified Windows-native Gemini transport boundary and the
  digest-bound reviews for the six successful Gemini 3.1 Flash-Lite fixtures.
  The four human averages are each 1.00/2.00; do not inflate this small sample
  into a broad factuality or non-sycophancy claim.
- Keep the evidence chat read-only and local.
- Use the memory index for curated documentation and project notes.
- Maintain the current 24-case response-quality and control-plane corpus; add cases only when a real failure mode is discovered or a policy contract changes.
- Convert inline C# harnesses into a normal test project.
- Create a short public demo video showing the control tower, not mythology.

### Achievable in 90 days

- Add an operator approval queue to the chat interface.
- Repeat the separately labelled live benchmark across additional models only when comparison has a concrete decision purpose; preserve raw local results and human scores.
- Add a signed or external timestamp anchor.
- Add a formal policy schema and policy regression tests.
- Support a second model provider without changing the execution boundary.
- Add reproducible CI for Python, C#, and Node verifiers.

### Not current goals

- Building a new general-purpose processor.
- Replacing IEEE-754 for all computation.
- Building a conscious, self-remembering LLM.
- Claiming cryptographic or physical breakthroughs without independent evidence.
- Deploying money movement, wallets, Web3 contracts, or autonomous external network access.

## 7. Tools and deployment choices

### Use now

- **Docker Desktop:** yes, as the local OS-level tool boundary. It is justified for controlled execution; it is not required for read-only search or math.
- **SQLite FTS5:** yes, for local retrieval before embeddings. It is fast, inspectable, dependency-free, and works offline.
- **Python + C# + Node:** retain all three where they independently validate the ledger format. Do not maintain three versions of every feature.
- **Git:** use one clean repository, a small changelog, and a documented release command.
- **Unified local tower:** use as the default UI; do not build a second dashboard unless it eliminates a measured limitation.

### Add later only when measured need exists

- Embeddings/vector search, after full-text search proves insufficient.
- LiteLLM or another model router, after the direct Gemini path is stable. The router must stay outside the execution authority boundary.
- A managed external timestamp or WORM anchor, when the product leaves one local machine.
- Security scanning and CI: Ruff, Bandit, Semgrep, CodeQL, dependency review, and signed releases.

## 8. Governance rules

1. A green model response is not evidence.
2. A successful command is not a safe command unless policy and isolation authorized it.
3. A hash chain is not tamper-proof unless its tail is anchored outside the attacker's control.
4. Exact math is not a proof of a product claim; it is a proof about arithmetic.
5. A deterministic context packet and its private snapshot prove what source
   context was supplied to a model, not that the model interpreted it correctly
   or answered truthfully. They are not a full prompt archive or deterministic
   model replay.
6. A new module must eliminate a demonstrated limitation, not rename an old one.
7. If a feature cannot state its inputs, outputs, failure modes, and test, it remains an experiment.

## Conclusion

The coherent project is now visible:

**A local, verifiable workbench for evidence-backed AI interaction and controlled agent execution.**

The strongest contribution is not that it makes models infallible. It makes their uncertainty and their actions inspectable. That is both useful and defensible.
