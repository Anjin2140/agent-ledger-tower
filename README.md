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
- **One local interface** — evidence chat, exact math, fleet verification, and
  the operator kill switch, and explicit release review now live behind one localhost page. Fleet launch is
  an explicit operator action, never a side effect of opening the page.

The controller and verifiers are dependency-free. Live tool execution additionally requires Docker Desktop so actions can run outside the controller process and without host credentials.

---

## First five minutes — use the local tower

This is the normal path if you want to use the work rather than run a technical
proof. Open PowerShell and paste:

```powershell
# clone the repo, then start the tower from inside it
git clone https://github.com/Anjin2140/agent-ledger-tower
cd agent-ledger-tower
powershell -ExecutionPolicy Bypass -File start_tower.ps1
```

Leave that window open, then open the address it prints: `http://127.0.0.1:8767`.
Nothing leaves your machine merely by opening the page, and the demonstration
fleet stays off until you explicitly select **Launch demo fleet**.

In the **Evidence chat** tab, try these in order:

1. `/search exact rational` — show source-hashed excerpts from the selected local material.
2. `/math 0.1 + 0.2 - 0.3` — calculate the result as an exact fraction, not a floating-point approximation.
3. Ask an ordinary question about the indexed sources. If secure Gemini access is available, it gives a read-only, cited answer; otherwise it returns the local evidence without pretending to be a model answer.
4. Select **View saved evidence** beneath the response to see the exact source packet used for that turn.
5. Open the **System** tab and select **Check release review** to confirm every shipped file has a review record.

The default launch indexes only the curated documentation and recovered notes.
To ask questions about the retained exact-math implementations, launch with:

```powershell
powershell -ExecutionPolicy Bypass -File start_tower.ps1 -IncludeWorkingSet
```

That adds `Code/regime_math`, `Code/RegimeMath`, and `Code/fixedpoint` to the
local index. Generated directories, virtual environments, build output, local
ledgers, and likely secret filenames are excluded. For a different, deliberately
selected source folder, use `-Source C:\path\to\folder`; do not point it at the
historical archive or a credential directory.

The saved evidence packet can contain excerpts from files you chose to index. It
is kept locally and excluded from Git, but is not encrypted by this package.

## Quickstart — run the whole thing

Start Docker Desktop once, then build the local worker image:

powershell -ExecutionPolicy Bypass -File setup_sandbox.ps1

After that, run the complete proof:

```bash
# Windows PowerShell
powershell -ExecutionPolicy Bypass -File run_all.ps1

# Or provision the reviewed local image only when it is missing, then run the proof
powershell -ExecutionPolicy Bypass -File run_all.ps1 -BuildSandbox

# macOS / Linux
./run_all.sh
```

This records a gated agent run, demonstrates the clearance gate blocking hostile
actions, performs two forgery attacks and catches them, then has **C# and Node
independently re-derive** the same ledger. The command exits `0` only when every
required stage passes. If the hard Docker boundary is unavailable, it exits
nonzero and refuses to present an agent trace as a contained-execution proof.

Before that proof runs, `component_review.py` verifies that every file admitted to
the release allowlist has one concrete review record: purpose, status, inputs,
outputs, failure mode, reuse path, test evidence, and an explicit non-claim.
`active_tree_review.py` also checks the development tree and fails closed on any
non-runtime file outside that reviewed allowlist; generated state and
administrative files are excluded only through reason-bearing entries in
`active_tree_exclusions.json`.
`release_hygiene.py` then verifies the manifest, required runtime ignores,
legacy-language cleanup, and common live credential patterns. It is deliberately
a small pre-publication guard, not a substitute for a professional secret scan or
security review.

## Create a clean standalone export

The parent RegimeOS workspace contains historical and archival material. To copy
only the reviewed control-tower source, tests, and documentation into a new
empty directory, run:

```powershell
powershell -ExecutionPolicy Bypass -File export_standalone.ps1
```

The exporter and review checker share `release_files.json` as their one allowlist,
then the exporter creates `RELEASE_MANIFEST.json` with a
SHA-256 hash for every copied file. It never overwrites a destination and does
not copy credentials, local ledgers, SQLite state, agent workspaces, build
output, or the historical archive.

The export also includes a GitHub Actions workflow that runs the same Linux
`run_all.sh` proof with Docker, Python, .NET, and Node. It has been exercised
locally through Git Bash; its first hosted execution remains an external
verification event, not a claim made in advance.

Read [COMPONENTS.md](COMPONENTS.md) for the plain-language review of every
released component: its purpose, evidence, current status, and limits. Read the
[architecture paper](VERIFIABLE_AI_WORKFLOWS.md) for the problem statement and
workflows, and [REVIEW_POLICY.md](REVIEW_POLICY.md) for the new-file admission
rules. The manual external handoff is documented in [PUBLISHING.md](PUBLISHING.md).

## Verify it yourself (don't trust — run)

```bash
py -3.13 agent_ledger.py                                 # write + replay + tamper-detect
dotnet run --project xrt_verify -- agent_ledger.jsonl    # C# re-derives every hash
node verify.js agent_ledger.jsonl                        # Node re-derives every hash
```

If the Python tail hash equals `b1ab8a01a00c` and both verifiers agree, the ledger
verified across three runtimes on *your* machine. The full byte-layout is in
[SPEC.md](SPEC.md) — enough to write your own verifier in any language with SHA-256.

## The pieces

| Capability          | Run it                              | Source |
|---------------------|-------------------------------------|--------|
| Audit root          | `py -3.13 agent_ledger.py`          | `agent_ledger.py`, `agent_notary.py` |
| Forgery resistance  | `py -3.13 forgery_demo.py`          | `agent_notary.py` |
| Clearance gate      | `py -3.13 policy_gate_demo.py`      | `policy_gate.py`, `default_policy.json` |
| Release-file review | `py -3.13 component_review.py`     | `component_review_registry.json`, `release_files.json` |
| Live agent loop     | `py -3.13 agent_loop.py`            | `agent_loop.py` (see [SETUP_GEMINI.md](SETUP_GEMINI.md)) |
| OS tool boundary    | `py -3.13 sandbox_demo.py --mode hard` | sandbox.py, sandbox_worker.py, Dockerfile.sandbox, SANDBOX.md |
| Fleet oversight     | `py -3.13 fleet_tower.py`           | `fleet_tower.py` |
| Unified local tower | `powershell -ExecutionPolicy Bypass -File start_tower.ps1` | `tower_console.py` → http://127.0.0.1:8767; recommended normal interface |
| Standalone operator view | `py -3.13 operator_console.py` | `operator_console.py` → http://127.0.0.1:8765; fleet-only view |
| Standalone evidence chat | `powershell -ExecutionPolicy Bypass -File start_chat.ps1` | `chat_console.py` → http://127.0.0.1:8766; chat-only view |
| Gemini configuration check | `py -3.13 gemini_preflight.py --live` | `gemini_config.py`, `gemini_preflight.py` — lists accessible models only; no prompt generation |
| Evaluation corpus | `py -3.13 evaluation_suite.py` | `evaluation_cases.json`, `evaluation_suite.py` — 24 deterministic response/policy cases |
| Live-model benchmark | `py -3.13 live_model_benchmark.py` | 6 fixed, human-scored fixtures; dry run by default |
| Independent verify  | C# `xrt_verify/`, Node `verify.js`  | + [SPEC.md](SPEC.md) |

## How it works

The model can propose actions but has no direct host capability. Policy-approved actions run one at a time in disposable, networkless containers that receive no API key and can write only to the assigned agent workspace. Each action gets a one-process limit, so it cannot fork a child process. A missing or malformed policy is deny-all; hard mode blocks the action if the container boundary is unavailable. See SANDBOX.md.

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

## Unified local tower (recommended)

For normal use, start one page instead of separate chat and fleet processes:

```powershell
powershell -ExecutionPolicy Bypass -File start_tower.ps1
```

Open `http://127.0.0.1:8767`. It provides evidence chat, exact rational math,
fleet status, verified action tails, and token-protected launch/kill/revive
controls. It does **not** start the demonstration fleet until you select
**Launch demo fleet**. Its System tab also provides an explicit Gemini
connection check; that request lists models only and never sends a prompt or
prints the API key. HTTPS verification remains mandatory. On Windows, a narrowly
destination-allowlisted helper may use the OS certificate verifier when Python
rejects an otherwise Windows-trusted local inspection CA; it is not a TLS
bypass. See [SETUP_GEMINI.md](SETUP_GEMINI.md).

## Standalone local evidence chat

For a single local workspace, run:

```powershell
powershell -ExecutionPolicy Bypass -File start_chat.ps1
```

Open `http://127.0.0.1:8766`. The chat can search source-hashed excerpts
(`/search`), calculate exact rationals (`/math 0.1 + 0.2 - 0.3`), and—only
if `GEMINI_API_KEY` is present—request a **read-only, structurally audited but
unverified** Gemini response with the retrieved excerpts attached. The audit
flags missing Evidence/Inference/Unknown sections, unused supplied citations,
and action claims that a read-only chat cannot truthfully make. It cannot
establish factual truth and it cannot execute tools. Use `agent_loop.py` for
the separate policy-gated action workflow.

When launched without `--source`, the chat indexes only this reviewed package.
Use one or more explicit `--source` folders for your own selected notes; it
never scans the whole machine by default.

Before an ordinary chat request can reach a model, the exact retrieved evidence
packet is saved locally as `evidence_packets/<sha256>.json`. The action ledger
stores only the packet digest and metadata, not the packet text, your question,
or the model response. Use the **View saved evidence** button (or
`/evidence <sha256>`) in chat to inspect that saved context later. These
snapshots may contain excerpts from your selected files,
are ignored by Git and the release exporter, and should remain private. They are
not encrypted by this package; rely on your Windows account and disk encryption
if that material is sensitive. If the
snapshot cannot be saved, the model request is withheld rather than using
unrecoverable context.

## Human-scored live-model benchmark

The deterministic corpus checks the controller contracts; it does **not** prove
that a model is factual or non-sycophantic. The separate benchmark therefore
starts safely in dry-run mode:

```powershell
py -3.13 live_model_benchmark.py
```

When you intentionally want to spend Gemini API quota on six fixed, harmless
fixtures, run `py -3.13 live_model_benchmark.py --live`. It writes local,
git-ignored response records with pending human scores. Review them with:

```powershell
py -3.13 review_live_benchmark.py --input live_benchmark_results.jsonl
```

After scoring, verify that every review still matches the exact response digest
and uses only integer 0–2 scores:

```powershell
py -3.13 review_live_benchmark.py --input live_benchmark_results.jsonl --validate live_benchmark_reviews.jsonl
```

If any model request fails, the benchmark exits nonzero and labels that row
`request_failed`; the scorer refuses to rate it as model behavior. Read the
safe `request_error` diagnostic, correct the connection/key/model setup, and
rerun before collecting human scores. A blank response is a failed experiment,
not partial credit for the model.

Before that six-prompt run, use `py -3.13 gemini_preflight.py --live`. It calls
Google's model-list endpoint only, never sends a prompt, never prints the key,
and confirms that the exact configured chat and agent model names are available
for `generateContent`.

The four human scores are evidence fidelity, uncertainty honesty, action-boundary
honesty, and non-sycophancy. Structural flags remain automatic; these four are
deliberately human judgments.

## Honest scope

This is a **reference implementation and prototype**, not a hardened product.

- The block hash is plain SHA-256 over a documented canonical layout — not a novel
  primitive, a *verifiable* one. That is the point.
- The anchor's strength equals the out-of-band-ness of where it is stored (an
  append-only store off-box, an external timestamp, a public chain, a printed
  hash) — no more. The code makes the check; the deployment makes the anchor
  trustworthy.
- The shipped policy is a small default-deny allowlist, not a complete enterprise policy. Tool handlers also apply structural validation and real-path confinement.

## Credit

The sample content references an external certificate-bound admission architecture
(SAB; He & Yu, 2026); it is cited, not claimed. This project is an independent
implementation of a general accountability layer for agent fleets.

## License

Apache-2.0 — see [LICENSE](LICENSE).
