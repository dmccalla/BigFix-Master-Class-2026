#requires -Version 5.1
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

<#
.SYNOPSIS
    Refresh uv.lock and requirements.txt with a 7-day dependency cooldown.

.DESCRIPTION
    Supply-chain protection: never lock a package version published in the
    last CooldownDays days. A malicious release is usually found and pulled
    within days, so waiting a week keeps it out of the Workbench.

    What this script does, in order:
      1. Computes the cutoff: today (UTC, start of day) minus CooldownDays.
      2. Rewrites [tool.uv].exclude-newer in pyproject.toml to that cutoff, so
         any later `uv lock` still respects it.
      3. Runs `uv lock --upgrade` at that cutoff to refresh uv.lock.
      4. Exports requirements.txt, the full pinned runtime set the launcher
         installs, from the new lock.

    Commit pyproject.toml, uv.lock and requirements.txt together, then run the
    full test suite. They describe the same dependency set at the same cutoff.

.PARAMETER CooldownDays
    Cooldown window in days. Default 7.

.PARAMETER UvPath
    Path to uv.exe when uv is not on PATH.

.EXAMPLE
    .\Build\refresh-lockfile.ps1
#>

param(
    [int]$CooldownDays = 7,
    [string]$UvPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$pyprojectPath = Join-Path $repoRoot "pyproject.toml"
if (-not (Test-Path -LiteralPath $pyprojectPath)) {
    throw "pyproject.toml not found at $pyprojectPath"
}

$uv = if ($UvPath) { $UvPath } else { (Get-Command uv -ErrorAction Stop).Source }
Write-Host "Using uv: $uv"

# Start of the UTC day keeps the cutoff stable for the whole day.
$cutoff = (Get-Date).ToUniversalTime().Date.AddDays(-$CooldownDays)
$cutoffIso = $cutoff.ToString("yyyy-MM-ddTHH:mm:ssZ")
Write-Host "Cooldown window: $CooldownDays days"
Write-Host "Refusing versions newer than: $cutoffIso"

# Read and write UTF-8 without a BOM. Windows PowerShell 5.1 defaults would
# mangle non-ASCII text or add a BOM that TOML readers reject.
$pyproject = [System.IO.File]::ReadAllText($pyprojectPath)
$pattern = '(?ms)(\[tool\.uv\][^\[]*?exclude-newer\s*=\s*")[^"]+(")'
if ($pyproject -notmatch $pattern) {
    throw "Could not find [tool.uv].exclude-newer in pyproject.toml."
}
$pyproject = [regex]::Replace($pyproject, $pattern, "`${1}$cutoffIso`${2}")
[System.IO.File]::WriteAllText(
    $pyprojectPath, $pyproject, (New-Object System.Text.UTF8Encoding($false))
)
Write-Host "Updated pyproject.toml [tool.uv].exclude-newer"

Push-Location $repoRoot
try {
    # --upgrade re-resolves every package to the newest version older than
    # the cutoff. Without it uv keeps the versions already locked.
    & $uv lock --upgrade --exclude-newer $cutoffIso
    if ($LASTEXITCODE -ne 0) { throw "uv lock failed (exit $LASTEXITCODE)" }

    & $uv export --no-dev --no-hashes --no-emit-project --frozen --output-file requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "uv export failed (exit $LASTEXITCODE)" }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Done. Review and commit pyproject.toml, uv.lock and requirements.txt,"
Write-Host "then run the full test suite."
