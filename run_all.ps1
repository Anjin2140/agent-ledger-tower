# run_all.ps1 — one command: sandbox + gate + three-runtime verification.
# Usage: powershell -ExecutionPolicy Bypass -File run_all.ps1 [-BuildSandbox]
param(
    [switch]$BuildSandbox
)

$demo   = $PSScriptRoot
$nodeV  = Join-Path $demo "verify.js"
$ledger = Join-Path $demo "agent_loop_ledger.jsonl"
$notary = Join-Path $demo "agent_loop_notary.log"

function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }

function Resolve-Python {
    # Do not trust a bare `python` lookup or the Windows `py` shim: PATH may
    # contain a shim that reports a runtime which is not actually installed.
    # Prefer the verified per-user installation used by this workstation.
    $cands = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe")
    )
    foreach ($c in $cands) {
        $exists = (Get-Command $c -ErrorAction SilentlyContinue) -or (Test-Path $c -ErrorAction SilentlyContinue)
        if (-not $exists) { continue }
        try {
            $v = & $c --version 2>&1
            if ($LASTEXITCODE -eq 0 -and "$v" -match "Python 3") { return $c }
        } catch { }
    }

    # The launcher is a fallback for clean machines where Python is installed
    # elsewhere. Validate both its exit code and the returned executable path.
    try {
        $resolved = (& py -3.13 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1).Trim()
        if ($LASTEXITCODE -eq 0 -and $resolved -and (Test-Path -LiteralPath $resolved)) {
            return $resolved
        }
    } catch { }
    return $null
}

$bar = "==================================================================="
Write-Host $bar
Write-Host " CONTROL TOWER PROOF: OS sandbox + policy + independent verification"
Write-Host $bar

if ($BuildSandbox) {
    & docker image inspect "agent-ledger-sandbox:1" *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Preflight: hard-sandbox image missing; building the reviewed pinned image."
        powershell -ExecutionPolicy Bypass -File (Join-Path $demo "setup_sandbox.ps1")
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Preflight FAILED: the hard-sandbox image could not be built."
            exit 1
        }
    } else {
        Write-Host "Preflight: hard-sandbox image is present."
    }
}

$unitOK = $false; $sandboxOK = $false; $pyOK = $false; $fleetOK = $false
$policyOK = $false; $forgeryOK = $false; $csOK = $false; $nodeOK = $false
$py = Resolve-Python

if ($py) {
    Write-Host ("verified Python: " + $py)
    $barePython = Get-Command python -ErrorAction SilentlyContinue
    if ($barePython -and $barePython.Source -ne $py) {
        Write-Host ("NOTICE: bare 'python' resolves elsewhere: " + $barePython.Source)
        Write-Host "        This proof deliberately uses the verified interpreter above."
    }
    Write-Host ""; Write-Host "[1/8] Python  - active-tree admission, release review, policy, sandbox, memory, math, and chat regression tests"
    $unitOK = $true
    & $py (Join-Path $demo "component_review.py")
    if ($LASTEXITCODE -ne 0) { $unitOK = $false }
    & $py (Join-Path $demo "active_tree_review.py")
    if ($LASTEXITCODE -ne 0) { $unitOK = $false }
    & $py (Join-Path $demo "release_hygiene.py") --allow-missing-manifest
    if ($LASTEXITCODE -ne 0) { $unitOK = $false }
    foreach ($test in @("test_component_review.py", "test_active_tree_review.py", "test_release_hygiene.py", "test_sandbox.py", "test_agent_loop_policy.py", "test_memory_index.py", "test_exact_math_tool.py", "test_response_quality.py", "test_evaluation_suite.py", "test_gemini_config.py", "test_live_model_benchmark.py", "test_chat_console.py", "test_fleet_tower.py", "test_tower_console.py")) {
        & $py (Join-Path $demo $test)
        if ($LASTEXITCODE -ne 0) { $unitOK = $false }
    }

    Write-Host ""; Write-Host "[2/8] Docker  - adversarial OS-boundary proof"
    & $py (Join-Path $demo "sandbox_demo.py") --mode hard
    if ($LASTEXITCODE -eq 0) { $sandboxOK = $true }

    if ($sandboxOK) {
        Write-Host ""; Write-Host "[3/8] Python  - gated agent run through hard sandbox + anchor"
        $hadMock = Test-Path Env:AGENT_FORCE_MOCK
        $oldMock = $env:AGENT_FORCE_MOCK
        $hadMode = Test-Path Env:AGENT_SANDBOX_MODE
        $oldMode = $env:AGENT_SANDBOX_MODE
        try {
            $env:AGENT_FORCE_MOCK = "1"
            $env:AGENT_SANDBOX_MODE = "hard"
            & $py (Join-Path $demo "agent_loop.py")
            if ($LASTEXITCODE -eq 0) { $pyOK = $true }
        } finally {
            if ($hadMock) { $env:AGENT_FORCE_MOCK = $oldMock } else { Remove-Item Env:AGENT_FORCE_MOCK -ErrorAction SilentlyContinue }
            if ($hadMode) { $env:AGENT_SANDBOX_MODE = $oldMode } else { Remove-Item Env:AGENT_SANDBOX_MODE -ErrorAction SilentlyContinue }
        }

        Write-Host ""; Write-Host "[4/8] Python  - hard-sandbox fleet audit"
        $hadMode = Test-Path Env:AGENT_SANDBOX_MODE
        $oldMode = $env:AGENT_SANDBOX_MODE
        try {
            $env:AGENT_SANDBOX_MODE = "hard"
            & $py (Join-Path $demo "fleet_tower.py")
            if ($LASTEXITCODE -eq 0) { $fleetOK = $true }
        } finally {
            if ($hadMode) { $env:AGENT_SANDBOX_MODE = $oldMode } else { Remove-Item Env:AGENT_SANDBOX_MODE -ErrorAction SilentlyContinue }
        }
    } else {
        Write-Host ""; Write-Host "[3-4/8] SKIPPED: hard Docker boundary is unavailable."
        Write-Host "        No action trace will be presented as a contained-agent proof."
    }

    Write-Host ""; Write-Host "[5/8] Python  - policy adjudication simulation"
    & $py (Join-Path $demo "policy_gate_demo.py")
    if ($LASTEXITCODE -eq 0) { $policyOK = $true }
    Write-Host ""; Write-Host "[6/8] Python  - forgery demo (rewrite from genesis + rollback)"
    & $py (Join-Path $demo "forgery_demo.py")
    if ($LASTEXITCODE -eq 0) { $forgeryOK = $true }
} else {
    Write-Host ""; Write-Host "[1-6/8] No working Python found - SKIPPED"
}

if (-not $pyOK) {
    Write-Host ""; Write-Host "[7/8] C#      - SKIPPED: no successful hard-gated action trace to verify"
} elseif (Have dotnet) {
    Write-Host ""; Write-Host "[7/8] C#      - independent re-derivation of the ledger + anchor"
    dotnet run --project (Join-Path $demo "xrt_verify") -- $ledger $notary
    if ($LASTEXITCODE -eq 0) { $csOK = $true }
} else {
    Write-Host ""; Write-Host "[7/8] dotnet not found - SKIPPED (install the .NET 8 SDK)"
}

if (-not $pyOK) {
    Write-Host ""; Write-Host "[8/8] Node    - SKIPPED: no successful hard-gated action trace to verify"
} elseif (Have node) {
    Write-Host ""; Write-Host "[8/8] Node    - second independent verifier (zero shared code)"
    node $nodeV $ledger $notary
    if ($LASTEXITCODE -eq 0) { $nodeOK = $true }
} else {
    Write-Host ""; Write-Host "[8/8] node not found - SKIPPED (install Node.js)"
}

function St($b) { if ($b) { "OK" } else { "skipped/failed" } }
Write-Host ""; Write-Host $bar
Write-Host " SUMMARY"
Write-Host ("   Policy/worker tests                  : " + (St $unitOK))
Write-Host ("   Docker OS boundary                   : " + (St $sandboxOK))
Write-Host ("   Python writer + gate + self-verify   : " + (St $pyOK))
Write-Host ("   Fleet audit under hard sandbox        : " + (St $fleetOK))
Write-Host ("   Policy adjudication simulation        : " + (St $policyOK))
Write-Host ("   Forgery / anchor detection            : " + (St $forgeryOK))
Write-Host ("   C# independent verify                : " + (St $csOK))
Write-Host ("   Node independent verify              : " + (St $nodeOK))
if ($unitOK -and $sandboxOK -and $pyOK -and $fleetOK -and $policyOK -and $forgeryOK -and $csOK -and $nodeOK) {
    Write-Host ""; Write-Host "   RESULT: hard-gated ledger verified across THREE runtimes."
    Write-Host $bar
    exit 0
} else {
    Write-Host ""; Write-Host "   RESULT: incomplete. If Docker is the failed line, start it and run setup_sandbox.ps1."
    Write-Host $bar
    exit 1
}
