<#
Create a clean, standalone Agent Ledger Tower export.

This is intentionally an allowlist copier, not a recursive archive command. It
never exports local ledgers, SQLite memory, agent workspaces, credentials,
Docker state, build output, or the larger historical workspace.

Usage:
  powershell -ExecutionPolicy Bypass -File export_standalone.ps1
  powershell -ExecutionPolicy Bypass -File export_standalone.ps1 -Destination C:\path\to\agent-ledger-tower
#>
param(
    [string]$Destination = (Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) "release\agent-ledger-tower")
)

$ErrorActionPreference = "Stop"
$source = [IO.Path]::GetFullPath($PSScriptRoot)
$destinationFull = [IO.Path]::GetFullPath($Destination)
if ($destinationFull -eq $source -or $destinationFull.StartsWith($source + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Destination must be outside the source package."
}
if (Test-Path -LiteralPath $destinationFull) {
    throw "Destination already exists. Choose a new empty destination; this export command never deletes or overwrites files."
}

$allowlistPath = Join-Path $source "release_files.json"
if (-not (Test-Path -LiteralPath $allowlistPath -PathType Leaf)) {
    throw "Release allowlist is missing: $allowlistPath"
}
$allowlist = Get-Content -LiteralPath $allowlistPath -Raw | ConvertFrom-Json
if ($allowlist.schema -ne "agent-ledger-tower-release-files-v1") {
    throw "Release allowlist has an unexpected schema."
}
if (-not $allowlist.files -or $allowlist.files.Count -eq 0) {
    throw "Release allowlist contains no files."
}

$seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$files = @()
foreach ($rawRelative in @($allowlist.files)) {
    if (-not ($rawRelative -is [string]) -or [string]::IsNullOrWhiteSpace($rawRelative)) {
        throw "Release allowlist contains an invalid file path."
    }
    $relative = $rawRelative.Replace("/", "\")
    if ([IO.Path]::IsPathRooted($relative) -or $relative -match "(^|[\\/])\.\.([\\/]|$)") {
        throw "Release allowlist path escapes the source package: $rawRelative"
    }
    if (-not $seen.Add($relative)) {
        throw "Release allowlist contains a duplicate path: $rawRelative"
    }
    $files += $relative
}

New-Item -ItemType Directory -Path $destinationFull | Out-Null
$manifest = @()
foreach ($relative in $files) {
    $input = Join-Path $source $relative
    if (-not (Test-Path -LiteralPath $input -PathType Leaf)) {
        throw "Required release file is missing: $relative"
    }
    $output = Join-Path $destinationFull $relative
    $parent = Split-Path $output -Parent
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Copy-Item -LiteralPath $input -Destination $output
    $manifest += [ordered]@{
        path = $relative.Replace("\", "/")
        sha256 = (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant()
        bytes = (Get-Item -LiteralPath $output).Length
    }
}

$release = [ordered]@{
    format = "agent-ledger-tower-release-v1"
    created_utc = [DateTime]::UtcNow.ToString("o")
    # Do not publish the creator's local absolute path in a public manifest.
    source = "standalone-export"
    files = $manifest
    exclusions = @("credentials", "local ledgers", "SQLite state", "agent workspace", "build output", "historical archive")
}
$manifestPath = Join-Path $destinationFull "RELEASE_MANIFEST.json"
$manifestJson = $release | ConvertTo-Json -Depth 4
# Write BOM-free UTF-8 so the generated manifest is identical on Windows and
# Linux CI. The checker still accepts an existing Windows BOM for compatibility.
[IO.File]::WriteAllText($manifestPath, $manifestJson, [Text.UTF8Encoding]::new($false))

Write-Host "Standalone export created: $destinationFull"
Write-Host ("Files copied: " + $manifest.Count)
Write-Host "Verify there: powershell -ExecutionPolicy Bypass -File run_all.ps1"
