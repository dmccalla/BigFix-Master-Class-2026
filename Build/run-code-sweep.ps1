#requires -Version 5.1
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

<#
.SYNOPSIS
    Run the full quality and security gate with the repo's private Python.

.DESCRIPTION
    Installs the developer tools into .venv when they are missing, then runs
    Build\run_code_sweep.py. Any additional arguments pass through, for
    example --apply-ruff-fixes or --fail-fast.

.EXAMPLE
    .\Build\run-code-sweep.ps1
#>

[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$SweepArgs = @()
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "No private environment at $python. Run the launcher once to create it."
}

& $python -c "import bandit, pip_audit, piplicenses, cyclonedx_py, vulture, mypy, ruff, pytest" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing developer tools into .venv..."
    & $python -m pip install --quiet --group dev -e $repoRoot
    if ($LASTEXITCODE -ne 0) {
        & $python -m pip install --quiet bandit cyclonedx-bom mypy pip-audit pip-licenses pytest ruff vulture
        if ($LASTEXITCODE -ne 0) { throw "Installing the developer tools failed." }
    }
}

& $python (Join-Path $repoRoot 'Build\run_code_sweep.py') @SweepArgs
exit $LASTEXITCODE
