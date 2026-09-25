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
#>

[CmdletBinding()]
param(
    [string]$OutputPath = "Dist\Releases",
    [switch]$ValidateOnly,
    [switch]$KeepStaging,
    [switch]$AllowDirtyTree
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
    $rootFiles = @("README.md", "CHANGELOG.md", "LICENSE", "NOTICE", "AUTHORS.md", "pyproject.toml", "requirements.txt")
    if ($rootFiles -contains $path) { return $true }

    $prefixes = @("App/", "Get/", "Inject/", "Lib/", "Assets/", "Fonts/", "Templates/", "SampleData/", "Tasks and Analyses/", "Utilities/", "Launchers/", "Docs/")
    if (-not ($prefixes | Where-Object { $path.StartsWith($_) })) { return $false }
    if ($path -match '(^|/)sitecustomize\.py$') { return $true }
    if ($path -match '(^|/)__pycache__/') { return $false }
    return $true
}

$version = Get-DeclaredVersion
if ($version -match '[-+]' -and -not $ValidateOnly) {
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

# SBOM and third-party notices from the environment the launcher builds.
$python = Get-RepoPython
Write-Host "Python  : $python"
& $python -m cyclonedx_py environment --of JSON --outfile (Join-Path $stagingPath "sbom.cyclonedx.json") $python
if ($LASTEXITCODE -ne 0) { throw "cyclonedx-py failed (exit $LASTEXITCODE)" }
$licensesJson = & $python -m piplicenses --format=json --with-urls
if ($LASTEXITCODE -ne 0) { throw "pip-licenses failed (exit $LASTEXITCODE)" }
$rows = $licensesJson | ConvertFrom-Json
$notices = @(
    "# Third-Party Notices",
    "",
    "Packages installed into the Workbench's private environment, with their",
    "declared licenses. Generated at packaging time from pip-licenses.",
    "",
    "| Package | Version | License | Project |",
    "|---|---|---|---|"
)
foreach ($row in ($rows | Sort-Object { $_.Name.ToLowerInvariant() })) {
    $project = if ($row.URL -and $row.URL -ne "UNKNOWN") { "<$($row.URL)>" } else { "" }
    $notices += "| $($row.Name) | $($row.Version) | $($row.License) | $project |"
}
$notices += ""
[IO.File]::WriteAllText((Join-Path $stagingPath "THIRD_PARTY_NOTICES.md"), ($notices -join "`n"), (New-Object Text.UTF8Encoding($false)))

$startHere = @"
$productName $version

1. Double-click Launchers\Run Diagnostics Workbench.cmd. The first run creates
   a private Python environment for the tool. Python 3.11 or newer is required.
2. On the Folders step, choose the sample data at SampleData\BigFix Master Class 2026
   to try the Workbench without a deployment, or your own collected data.
3. Read the guide in Docs before class.

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
