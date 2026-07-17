# OS-level sandbox — making the gate the only door

The policy gate decides **which** actions may run. The sandbox bounds **what** a
running tool can touch, so an effect that tries to leave the mediated tool
interface dies at the OS boundary instead of at a regex. Tools never run in the
controller: `SandboxExecutor` launches `sandbox_worker.py` as a **separate
process**, so tool code cannot reach the controller, the policy, or the ledger.

## Two tiers (chosen by `mode`)

| Tier | How | `hard_boundary` | Use |
|------|-----|-----------------|-----|
| `hard` (default) | Docker container (`Dockerfile.sandbox`): `--network none`, read-only root, non-root `USER 65532`, pid/memory caps, `python -I` | **True** | the real boundary |
| `native` | subprocess: scrubbed env + kernel `RLIMIT_*` + realpath jail + network/spawn guards | **False** | dev / no-Docker; honest soft boundary |

`describe()` never overclaims: in `native` it reports `hard_boundary: False`; in
`hard` with Docker missing it reports `tier: "unavailable"` and **fails closed**
(the action does not run) rather than silently degrading to the soft tier.

## What is stopped

- **Path escape** — realpath jail rejects `..`, absolute paths, and symlinks.
- **Unknown tool** — only registered tools execute; anything else is BLOCKED.
- **Network** — denied unless explicitly granted (`--network none` in hard tier).
- **Child processes** — fork/exec/spawn denied.
- **Oversize writes** — kernel `RLIMIT_FSIZE`.
- **Compute bombs** — kernel `RLIMIT_CPU`; per-action wall-clock timeout (fail-closed).
- **Host-file access** — confined to the per-action workspace only.
- **Secret leakage** — the child environment is stripped of every secret-looking
  variable name; `_probe_environment` proves none crossed (`secret_names_present == []`).

Everything is **default-deny** and **fail-closed**: if the OS kills the worker, or
Docker is unavailable in hard mode, the controller records the action as BLOCKED.
Every verdict — EXECUTED or BLOCKED — is written to the tamper-evident ledger and
is verifiable in another runtime.

## Honest limits (and the path to stronger isolation)

The kernel `RLIMIT_*` caps and the Docker container are real OS enforcement. The
native tier's network/spawn guards are Python-level — they stop ordinary tool code
but a native-code exploit could evade them, which is exactly why native reports
`hard_boundary: False` and production runs use `hard`. Docker reduces capability;
it does not secure an unpatched host or replace a production isolation review. For
hostile multi-tenant workloads add seccomp-bpf + user namespaces or a stronger
isolator (gVisor/Firecracker); on Windows, Job Objects / Windows Sandbox.
