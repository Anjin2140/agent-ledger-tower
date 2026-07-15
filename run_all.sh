#!/usr/bin/env bash
# run_all.sh — one command: control-tower demo + three-runtime verification.
demo="$(cd "$(dirname "$0")" && pwd)"
nodeV="$demo/verify.js"
ledger="$demo/agent_loop_ledger.jsonl"
notary="$demo/agent_loop_notary.log"
have() { command -v "$1" >/dev/null 2>&1; }
PY=""; have python3 && PY=python3 || { have python && PY=python; }
bar="==================================================================="

echo "$bar"; echo " CONTROL TOWER PROOF: clearance + three-runtime verification"; echo "$bar"
pyOK=1; csOK=1; nodeOK=1

if [ -n "$PY" ]; then
  echo; echo "[1/5] Python  - gated agent run (policy clears each action) + anchor"
  "$PY" "$demo/agent_loop.py"; [ $? -eq 0 ] && pyOK=0
  echo; echo "[2/5] Python  - clearance demo (safe + hostile proposals, allow/deny recorded)"
  "$PY" "$demo/policy_gate_demo.py"
  echo; echo "[3/5] Python  - forgery demo (rewrite from genesis + rollback)"
  "$PY" "$demo/forgery_demo.py"
else echo; echo "[1-3/5] Python not found - SKIPPED"; fi

if have dotnet; then
  echo; echo "[4/5] C#      - independent re-derivation of the ledger + anchor"
  dotnet run --project "$demo/xrt_verify" -- "$ledger" "$notary"; [ $? -eq 0 ] && csOK=0
else echo; echo "[4/5] dotnet not found - SKIPPED (install the .NET 8 SDK)"; fi

if have node; then
  echo; echo "[5/5] Node    - second independent verifier (zero shared code)"
  node "$nodeV" "$ledger" "$notary"; [ $? -eq 0 ] && nodeOK=0
else echo; echo "[5/5] node not found - SKIPPED (install Node.js)"; fi

st() { [ "$1" -eq 0 ] && echo "OK" || echo "skipped/failed"; }
echo; echo "$bar"; echo " SUMMARY"
echo "   Python  writer + gate + self-verify : $(st $pyOK)"
echo "   C#   independent verify             : $(st $csOK)"
echo "   Node independent verify             : $(st $nodeOK)"
if [ $pyOK -eq 0 ] && [ $csOK -eq 0 ] && [ $nodeOK -eq 0 ]; then
  echo; echo "   RESULT: gated ledger verified across THREE runtimes - author-independent."
else
  echo; echo "   RESULT: partial - install/resolve any skipped runtime to complete the proof."
fi
echo "$bar"
