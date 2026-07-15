# run_all.ps1 — one command: control-tower demo + three-runtime verification.
# Usage:  powershell -ExecutionPolicy Bypass -File run_all.ps1
$demo   = $PSScriptRoot
$nodeV  = Join-Path $demo "verify.js"
$ledger = Join-Path $demo "agent_loop_ledger.jsonl"
$notary = Join-Path $demo "agent_loop_notary.log"

function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }

# Pick a REAL Python, not the empty Microsoft Store stub.
function Resolve-Python {
    $cands = @("py", "python", "python3",
               (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"))
    foreach ($c in $cands) {
        $exists = (Get-Command $c -ErrorAction SilentlyContinue) -or (Test-Path $c -ErrorAction SilentlyContinue)
        if (-not $exists) { continue }
        try {
            $v = & $c --version 2>&1
            if ($LASTEXITCODE -eq 0 -and "$v" -match "Python 3") { return $c }
        } catch { }
    }
    return $null
}

$bar = "==================================================================="
Write-Host $bar
Write-Host " CONTROL TOWER PROOF: clearance + three-runtime verification"
Write-Host $bar

$pyOK = $false; $csOK = $false; $nodeOK = $false
$py = Resolve-Python

if ($py) {
    Write-Host "`n[1/5] Python  - gated agent run (policy clears each action) + anchor"
    Write-Host ("      using: " + $py)
    & $py (Join-Path $demo "agent_loop.py"); if ($LASTEXITCODE -eq 0) { $pyOK = $true }
    Write-Host "`n[2/5] Python  - clearance demo (safe + hostile proposals, allow/deny recorded)"
    & $py (Join-Path $demo "policy_gate_demo.py")
    Write-Host "`n[3/5] Python  - forgery demo (rewrite from genesis + rollback)"
    & $py (Join-Path $demo "forgery_demo.py")
} else {
    Write-Host "`n[1-3/5] No working Python found - SKIPPED (install Python 3 from python.org, or use: py agent_loop.py)"
}

if (Have dotnet) {
    Write-Host "`n[4/5] C#      - independent re-derivation of the ledger + anchor"
    dotnet run --project (Join-Path $demo "xrt_verify") -- $ledger $notary
    if ($LASTEXITCODE -eq 0) { $csOK = $true }
} else {
    Write-Host "`n[4/5] dotnet not found - SKIPPED (install the .NET 8 SDK)"
}

if (Have node) {
    Write-Host "`n[5/5] Node    - second independent verifier (zero shared code)"
    node $nodeV $ledger $notary
    if ($LASTEXITCODE -eq 0) { $nodeOK = $true }
} else {
    Write-Host "`n[5/5] node not found - SKIPPED (install Node.js)"
}

function St($b) { if ($b) { "OK" } else { "skipped/failed" } }
Write-Host "`n$bar"
Write-Host " SUMMARY"
Write-Host ("   Python  writer + gate + self-verify : " + (St $pyOK))
Write-Host ("   C#   independent verify             : " + (St $csOK))
Write-Host ("   Node independent verify             : " + (St $nodeOK))
if ($pyOK -and $csOK -and $nodeOK) {
    Write-Host "`n   RESULT: gated ledger verified across THREE runtimes - author-independent."
} else {
    Write-Host "`n   RESULT: partial - install/resolve any skipped runtime to complete the proof."
}
Write-Host $bar
