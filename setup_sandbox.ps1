# Build the local, dependency-free tool sandbox image.
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot

docker info | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is installed but its engine is not running. Start Docker Desktop and retry."
}

docker build --file (Join-Path $repo "Dockerfile.sandbox") --tag "agent-ledger-sandbox:1" $repo
if ($LASTEXITCODE -ne 0) { throw "Sandbox image build failed." }

Write-Host "Sandbox image ready: agent-ledger-sandbox:1"
Write-Host "Run: py -3.13 sandbox_demo.py --mode hard"
