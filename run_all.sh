#!/usr/bin/env sh
demo="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
nodeV="$demo/verify.js"
ledger="$demo/agent_loop_ledger.jsonl"
notary="$demo/agent_loop_notary.log"
have() { command -v "$1" >/dev/null 2>&1; }
PY=""; have python3 && PY=python3 || { have python && PY=python; }
bar="==================================================================="

echo "$bar"; echo " CONTROL TOWER PROOF: OS sandbox + policy + independent verification"; echo "$bar"
if [ "${BUILD_SANDBOX:-0}" = "1" ]; then
  if ! docker image inspect agent-ledger-sandbox:1 >/dev/null 2>&1; then
    echo "Preflight: hard-sandbox image missing; building the reviewed pinned image."
    "$demo/setup_sandbox.sh" || exit 1
  else
    echo "Preflight: hard-sandbox image is present."
  fi
fi
unitOK=1; sandboxOK=1; pyOK=1; fleetOK=1; policyOK=1; forgeryOK=1; csOK=1; nodeOK=1

if [ -n "$PY" ]; then
  echo; echo "[1/8] Python  - release review, policy, sandbox, memory, math, and chat regression tests"
  unitOK=0
  "$PY" "$demo/component_review.py" || unitOK=1
  "$PY" "$demo/release_hygiene.py" --allow-missing-manifest || unitOK=1
  for test in test_component_review.py test_release_hygiene.py test_sandbox.py test_agent_loop_policy.py test_memory_index.py test_exact_math_tool.py test_response_quality.py test_evaluation_suite.py test_gemini_config.py test_live_model_benchmark.py test_chat_console.py test_fleet_tower.py test_tower_console.py; do
    "$PY" "$demo/$test" || unitOK=1
  done
  echo; echo "[2/8] Docker  - adversarial OS-boundary proof"
  "$PY" "$demo/sandbox_demo.py" --mode hard; [ $? -eq 0 ] && sandboxOK=0
  if [ $sandboxOK -eq 0 ]; then
    echo; echo "[3/8] Python  - gated agent run through hard sandbox + anchor"
    AGENT_FORCE_MOCK=1 AGENT_SANDBOX_MODE=hard "$PY" "$demo/agent_loop.py"; [ $? -eq 0 ] && pyOK=0
    echo; echo "[4/8] Python  - hard-sandbox fleet audit"
    AGENT_SANDBOX_MODE=hard "$PY" "$demo/fleet_tower.py"; [ $? -eq 0 ] && fleetOK=0
  else
    echo; echo "[3-4/8] SKIPPED: hard Docker boundary is unavailable."
    echo "        No action trace will be presented as a contained-agent proof."
  fi
  echo; echo "[5/8] Python  - policy adjudication simulation"
  "$PY" "$demo/policy_gate_demo.py"; [ $? -eq 0 ] && policyOK=0
  echo; echo "[6/8] Python  - forgery demo"
  "$PY" "$demo/forgery_demo.py"; [ $? -eq 0 ] && forgeryOK=0
else echo; echo "[1-6/8] Python not found - SKIPPED"; fi

if [ $pyOK -ne 0 ]; then
  echo; echo "[7/8] C#      - SKIPPED: no successful hard-gated action trace to verify"
elif have dotnet; then
  echo; echo "[7/8] C#      - independent ledger + anchor verification"
  dotnet run --project "$demo/xrt_verify" -- "$ledger" "$notary"; [ $? -eq 0 ] && csOK=0
else echo; echo "[7/8] dotnet not found - SKIPPED"; fi

if [ $pyOK -ne 0 ]; then
  echo; echo "[8/8] Node    - SKIPPED: no successful hard-gated action trace to verify"
elif have node; then
  echo; echo "[8/8] Node    - independent ledger + anchor verification"
  node "$nodeV" "$ledger" "$notary"; [ $? -eq 0 ] && nodeOK=0
else echo; echo "[8/8] node not found - SKIPPED"; fi

st() { [ "$1" -eq 0 ] && echo "OK" || echo "skipped/failed"; }
echo; echo "$bar"; echo " SUMMARY"
echo "   Policy/worker tests                : $(st $unitOK)"
echo "   Docker OS boundary                 : $(st $sandboxOK)"
echo "   Python writer + gate + self-verify : $(st $pyOK)"
echo "   Fleet audit under hard sandbox      : $(st $fleetOK)"
echo "   Policy adjudication simulation      : $(st $policyOK)"
echo "   Forgery / anchor detection          : $(st $forgeryOK)"
echo "   C# independent verify              : $(st $csOK)"
echo "   Node independent verify            : $(st $nodeOK)"
if [ $unitOK -eq 0 ] && [ $sandboxOK -eq 0 ] && [ $pyOK -eq 0 ] && [ $fleetOK -eq 0 ] && [ $policyOK -eq 0 ] && [ $forgeryOK -eq 0 ] && [ $csOK -eq 0 ] && [ $nodeOK -eq 0 ]; then
  echo; echo "   RESULT: hard-gated ledger verified across THREE runtimes."
  echo "$bar"
  exit 0
else
  echo; echo "   RESULT: incomplete. If Docker failed, start it and run setup_sandbox.sh."
  echo "$bar"
  exit 1
fi
