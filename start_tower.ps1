param(
    [switch]$Help,
    [int]$Port = 8767,
    [switch]$IncludeWorkingSet,
    [string[]]$Source = @()
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$root = Split-Path (Split-Path $here -Parent) -Parent
$docs = Join-Path $root "Docs"
$notes = Join-Path $root "MY_WORK\text"

if ($Help) {
    Write-Host "Starts one local page for evidence chat and fleet oversight on http://127.0.0.1:$Port"
    Write-Host "It does not launch a fleet until the operator clicks Launch demo fleet."
    Write-Host "Use -IncludeWorkingSet to add the retained math directories to retrieval."
    Write-Host "Use -Source <directory> to add an explicitly selected source directory."
    exit 0
}

$fallback = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"
$python = $null
if (Test-Path -LiteralPath $fallback -PathType Leaf) {
    # Prefer the verified per-user interpreter. A child PowerShell can inherit
    # a different py launcher configuration even when the interpreter exists.
    $python = $fallback
} else {
    $pyOutput = & py -3.13 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $pyOutput) {
        $python = ($pyOutput | Select-Object -First 1).Trim()
    }
    if (-not $python -or -not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Python 3.13 was not found. Install it from python.org or repair the 'py -3.13' launcher."
    }
}

$launchArgs = @((Join-Path $here "tower_console.py"), "--port", "$Port")
$candidates = @($docs, $notes)
if ($IncludeWorkingSet) {
    $candidates += @(
        (Join-Path $root "Code\regime_math"),
        (Join-Path $root "Code\RegimeMath"),
        (Join-Path $root "Code\fixedpoint")
    )
}
foreach ($selected in @($Source)) {
    if (-not (Test-Path -LiteralPath $selected -PathType Container)) {
        throw "Selected source directory is missing or is not a directory: $selected"
    }
    $candidates += $selected
}
$seenSources = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$sourceCount = 0
foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate -PathType Container) {
        $resolved = [IO.Path]::GetFullPath($candidate)
        if ($seenSources.Add($resolved)) {
            $launchArgs += @("--source", $resolved)
            $sourceCount += 1
        }
    }
}
if ($sourceCount -eq 0) { $launchArgs += @("--source", $here) }

Write-Host "Starting unified local tower..."
Write-Host "Open: http://127.0.0.1:$Port"
Write-Host "Use Ctrl+C in this window to stop it."
& $python @launchArgs
