param(
    [switch]$Help,
    [int]$Port = 8766
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$root = Split-Path (Split-Path $here -Parent) -Parent
$docs = Join-Path $root "Docs"
$notes = Join-Path $root "MY_WORK\text"

if ($Help) {
    Write-Host "Starts the local evidence chat on http://127.0.0.1:$Port"
    Write-Host "It indexes Docs and MY_WORK\text only. It does not execute agent tools."
    exit 0
}

$python = (& py -3.13 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1).Trim()
if (-not $python -or -not (Test-Path -LiteralPath $python)) {
    $fallback = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"
    if (Test-Path -LiteralPath $fallback) {
        $python = $fallback
    } else {
        throw "Python 3.13 was not found. Install it from python.org or repair the 'py -3.13' launcher."
    }
}

Write-Host "Starting local evidence chat..."
Write-Host "Open: http://127.0.0.1:$Port"
Write-Host "Use Ctrl+C in this window to stop it."
$launchArgs = @((Join-Path $here "chat_console.py"), "--port", "$Port")
$sourceCount = 0
foreach ($candidate in @($docs, $notes)) {
    if (Test-Path -LiteralPath $candidate -PathType Container) {
        $launchArgs += @("--source", $candidate)
        $sourceCount += 1
    }
}
if ($sourceCount -eq 0) {
    # Standalone export: index only the reviewed package, never the whole disk.
    $launchArgs += @("--source", $here)
}
& $python @launchArgs
