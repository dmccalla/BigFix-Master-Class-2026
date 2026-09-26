# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

<#
.SYNOPSIS
    Build the release package uploaded to GitHub Releases.

.DESCRIPTION
    Stages the tracked files an attendee needs, generates the CycloneDX SBOM
    and the third-party license notices from the current environment, writes
    START_HERE.txt and a release manifest with a SHA-256 per file, zips the
    staging folder and writes the zip's SHA-256 beside it.

    Refuses a dirty working tree and a development (-dev) version, so a
    package always corresponds to a commit that can be tagged.

.EXAMPLE
    .\Build\package_release.ps1
    Packages the version declared in pyproject.toml.

.EXAMPLE
    .\Build\package_release.ps1 -ValidateOnly
    Lists what would be packaged without building anything.

.EXAMPLE
    .\Build\package_release.ps1 -AllowDevVersion -AllowDirtyTree
    Local test build of a development version. Never upload one of these.
#>

[CmdletBinding()]
param(
    [string]$OutputPath = "Dist\Releases",
    [switch]$ValidateOnly,
    [switch]$KeepStaging,
    [switch]$AllowDirtyTree,
    [switch]$AllowDevVersion
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$pyprojectPath = Join-Path $repoRoot "pyproject.toml"
$productName = "Master Class Diagnostics Workbench"
$packageStem = "Master-Class-Diagnostics-Workbench"

function Get-DeclaredVersion {
    $text = Get-Content -Raw -Encoding utf8 -LiteralPath $pyprojectPath
    $match = [regex]::Match($text, '(?m)^version\s*=\s*"([^"]+)"')
    if (-not $match.Success) {
        throw "Could not read project.version from $pyprojectPath"
    }
    $match.Groups[1].Value
}

function Get-RepoPython {
    $venv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv) { return $venv }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $python) { throw "Python was not found. Run the launcher once to create .venv." }
    $python.Source
}

function Test-IncludedTrackedFile {
    param([string]$RelativePath)

    $path = $RelativePath.Replace("\", "/")
    $rootFiles = @("README.md", "CHANGELOG.md", "LICENSE", "NOTICE", "AUTHORS.md", "SECURITY.md", "pyproject.toml", "requirements.txt")
    if ($rootFiles -contains $path) { return $true }

    $prefixes = @("App/", "Get/", "Inject/", "Lib/", "Assets/", "Fonts/", "Templates/", "SampleData/", "Tasks and Analyses/", "Utilities/", "Launchers/", "Docs/")
    if (-not ($prefixes | Where-Object { $path.StartsWith($_) })) { return $false }
    if ($path -match '(^|/)sitecustomize\.py$') { return $true }
    if ($path -match '(^|/)__pycache__/') { return $false }
    return $true
}

$version = Get-DeclaredVersion
if ($version -match '[-+]' -and -not $ValidateOnly -and -not $AllowDevVersion) {
    throw "Refusing to package development version '$version'. Cut the release first (see Docs/Release_Process.md)."
}

$status = & git -C $repoRoot status --porcelain
if ($status -and -not $AllowDirtyTree -and -not $ValidateOnly) {
    throw "The working tree has uncommitted changes. Commit or stash them, or pass -AllowDirtyTree for a local test build."
}

$trackedFiles = & git -C $repoRoot ls-files
$includedFiles = @($trackedFiles | Where-Object { Test-IncludedTrackedFile $_ })

$required = @(
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "NOTICE",
    "requirements.txt",
    "Launchers/Run Diagnostics Workbench.cmd",
    "App/diagnostics_workbench_ui.py",
    "App/run_diagnostics.py",
    "Utilities/MXFillDBPerf.exe",
    "Templates/Diagnostics_Style_Template.docx"
)
foreach ($path in $required) {
    if ($includedFiles -notcontains $path) {
        throw "Required release file is not tracked or not included: $path"
    }
}

Write-Host "Product : $productName"
Write-Host "Version : $version"
Write-Host "Files   : $($includedFiles.Count) tracked files"
if ($ValidateOnly) {
    $includedFiles | ForEach-Object { Write-Host "  $_" }
    return
}

$outputRoot = Join-Path $repoRoot $OutputPath
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
$stagingPath = Join-Path $outputRoot "$packageStem-$version"
$zipPath = "$stagingPath.zip"
$checksumPath = "$zipPath.sha256"
foreach ($stale in @($stagingPath, $zipPath, $checksumPath)) {
    if (Test-Path -LiteralPath $stale) { Remove-Item -Recurse -Force -LiteralPath $stale }
}
New-Item -ItemType Directory -Force -Path $stagingPath | Out-Null

foreach ($relativePath in $includedFiles) {
    $source = Join-Path $repoRoot $relativePath
    $destination = Join-Path $stagingPath $relativePath
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination
}

# SBOM and third-party notices describe exactly what the launcher installs:
# a throwaway environment built from requirements.txt alone. The SBOM tools
# stay in the repo's own environment and inspect that runtime environment,
# so developer tools never leak into the inventory attendees receive.
$toolPython = Get-RepoPython
& $toolPython -c "import cyclonedx_py, piplicenses" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $toolPython -m pip install --quiet --disable-pip-version-check cyclonedx-bom pip-licenses
    if ($LASTEXITCODE -ne 0) { throw "Installing the SBOM tools failed (exit $LASTEXITCODE)" }
}
$sbomEnv = Join-Path $outputRoot "_sbom_env"
if (Test-Path -LiteralPath $sbomEnv) { Remove-Item -Recurse -Force -LiteralPath $sbomEnv }
Write-Host "Building the runtime-only environment for the SBOM..."
& $toolPython -m venv $sbomEnv
if ($LASTEXITCODE -ne 0) { throw "Could not create the SBOM environment (exit $LASTEXITCODE)" }
$runtimePython = Join-Path $sbomEnv "Scripts\python.exe"
& $runtimePython -m pip install --quiet --disable-pip-version-check -r (Join-Path $repoRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Installing requirements.txt into the SBOM environment failed (exit $LASTEXITCODE)" }
& $toolPython -m cyclonedx_py environment --of JSON -o (Join-Path $stagingPath "sbom.cyclonedx.json") $runtimePython
if ($LASTEXITCODE -ne 0) { throw "cyclonedx-py failed (exit $LASTEXITCODE)" }
# The notices are written from inside the runtime environment so the
# inventory is exactly what the launcher installs. See the script's docstring
# for why pip-licenses cannot be pointed at it from here.
& $runtimePython (Join-Path $repoRoot "Build\third_party_notices.py") (Join-Path $stagingPath "THIRD_PARTY_NOTICES.md") --ignore pip
if ($LASTEXITCODE -ne 0) { throw "Writing the third-party notices failed (exit $LASTEXITCODE)" }
Remove-Item -Recurse -Force -LiteralPath $sbomEnv

$startHere = @"
$productName $version

1. Double-click Launchers\Run Diagnostics Workbench.cmd. The first run creates
   a private Python environment for the tool. Python 3.11 or newer is required.
2. On the Folders step, choose the sample data at SampleData\BigFix Master Class 2026
   to try the Workbench without a deployment, or your own collected data.
3. Read Docs\Getting_Started.md before class. Docs\Data_Collection.md describes
   the files each module needs.

Release notes are in CHANGELOG.md. The software bill of materials is
sbom.cyclonedx.json and the license inventory is THIRD_PARTY_NOTICES.md.
"@
[IO.File]::WriteAllText((Join-Path $stagingPath "START_HERE.txt"), $startHere, (New-Object Text.UTF8Encoding($false)))

$sourceCommit = (& git -C $repoRoot rev-parse HEAD).Trim()
$manifestFiles = @(
    Get-ChildItem -Recurse -File -LiteralPath $stagingPath |
        Sort-Object FullName |
        ForEach-Object {
            [ordered]@{
                path = $_.FullName.Substring($stagingPath.Length + 1).Replace("\", "/")
                bytes = $_.Length
                sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
            }
        }
)
$manifest = [ordered]@{
    product = $productName
    version = $version
    source_commit = $sourceCommit
    created_utc = [DateTime]::UtcNow.ToString("o")
    files = $manifestFiles
}
[IO.File]::WriteAllText((Join-Path $stagingPath "release-manifest.json"), ($manifest | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding($false)))

Compress-Archive -LiteralPath $stagingPath -DestinationPath $zipPath -CompressionLevel Optimal
$zipHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash.ToLowerInvariant()
[IO.File]::WriteAllText($checksumPath, "$zipHash  $([IO.Path]::GetFileName($zipPath))`n", (New-Object Text.UTF8Encoding($false)))

if (-not $KeepStaging) {
    Remove-Item -Recurse -Force -LiteralPath $stagingPath
}

Write-Host "Release archive : $zipPath"
Write-Host "SHA-256 file    : $checksumPath"
