# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
# Shared release support. Dot-source from package_release.ps1.

function Get-LargePerfmonSampleFiles {
    param([string]$SourceDirectory, [string]$ApplicationRoot)

    $source = $SourceDirectory
    if ([string]::IsNullOrWhiteSpace($source)) { $source = $env:BIGFIX_LARGE_PERFMON_SAMPLE_DIR }
    if ([string]::IsNullOrWhiteSpace($source)) { $source = 'LocalSamples\Large_Perfmon' }
    if (-not [IO.Path]::IsPathRooted($source)) { $source = Join-Path $ApplicationRoot $source }
    $source = [IO.Path]::GetFullPath($source)
    if (-not (Test-Path -LiteralPath $source -PathType Container)) {
        throw "Large Perfmon sample folder is missing: $source. Supply -LargePerfmonSamplePath, set BIGFIX_LARGE_PERFMON_SAMPLE_DIR, or use -SkipLargePerfmonSamples for a package without this optional download."
    }
    for ($item = Get-Item -Force -LiteralPath $source; $null -ne $item; $item = $item.Parent) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Refusing a large-sample source through a reparse point: $($item.FullName)"
        }
    }
    $files = @(Get-ChildItem -LiteralPath $source -File -Force | Where-Object { $_.Extension -ieq '.blg' } | Sort-Object Name)
    if ($files.Count -eq 0) { throw "No BLG files found in large Perfmon sample folder: $source" }
    foreach ($file in $files) {
        if ($file.Length -eq 0 -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Large Perfmon sample must be a nonempty regular file: $($file.FullName)"
        }
    }
    $files
}

function New-LargePerfmonSampleArchive {
    param(
        [IO.FileInfo[]]$Files,
        [string]$OutputDirectory,
        [string]$Version,
        [string]$ProductName,
        [string]$SourceCommit,
        [string]$ArchiveRoot = 'SampleData/Large_Perfmon'
    )

    if ($Files.Count -eq 0) { throw 'A large Perfmon archive needs at least one BLG.' }
    if ($Version -notmatch '^[0-9A-Za-z][0-9A-Za-z.+-]*$') { throw 'Unsafe sample archive version.' }
    $ArchiveRoot = $ArchiveRoot.Replace('\', '/').TrimEnd('/')
    if ($ArchiveRoot -match '(^/|:|(^|/)(\.|\.\.)(/|$)|//)' -or [string]::IsNullOrWhiteSpace($ArchiveRoot)) {
        throw 'Sample archive root must be a relative folder without traversal.'
    }
    $output = [IO.Path]::GetFullPath($OutputDirectory)
    New-Item -ItemType Directory -Force -Path $output | Out-Null
    $archivePath = Join-Path $output "Sample-Data-Perfmon-Large-$Version.zip"
    $checksumPath = "$archivePath.sha256"
    foreach ($target in @($archivePath, $checksumPath)) {
        if (Test-Path -LiteralPath $target) {
            $item = Get-Item -Force -LiteralPath $target
            if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw "Refusing to replace a directory or reparse point: $target"
            }
        }
    }
    $temporary = Join-Path $output ('.perfmon-' + [Guid]::NewGuid().ToString('N') + '.zip')
    $records = New-Object 'Collections.Generic.List[object]'
    $encoding = New-Object Text.UTF8Encoding($false)
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = $null
    try {
        $archive = [IO.Compression.ZipFile]::Open($temporary, [IO.Compression.ZipArchiveMode]::Create)
        foreach ($file in $Files) {
            $inputStream = [IO.File]::Open($file.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
            $entryStream = $null
            $hasher = [Security.Cryptography.SHA256]::Create()
            try {
                # Hold a read-only handle while hashing and archiving the same bytes.
                $hash = ([BitConverter]::ToString($hasher.ComputeHash($inputStream))).Replace('-', '').ToLowerInvariant()
                $inputStream.Position = 0
                $name = "$ArchiveRoot/$($file.Name)"
                $entry = $archive.CreateEntry($name, [IO.Compression.CompressionLevel]::Optimal)
                $entryStream = $entry.Open()
                $inputStream.CopyTo($entryStream)
                $records.Add([ordered]@{ path = $name; bytes = $inputStream.Length; sha256 = $hash })
            } finally {
                if ($null -ne $entryStream) { $entryStream.Dispose() }
                $hasher.Dispose()
                $inputStream.Dispose()
            }
        }
        $readme = @"
$ProductName ${Version}: optional large Perfmon samples

Extract this ZIP into the same folder as the application package.
The BLG files are in $ArchiveRoot. Select a BLG directly in the Perfmon
module when you want to test the larger capture. The normal small sample
folder stays separate and continues to work without this download.

These files are demonstration evidence. Use the capture's own dates and
computer metadata when testing. They are not current deployment measurements.
"@
        $readmeBytes = $encoding.GetBytes($readme)
        $entry = $archive.CreateEntry('README.txt')
        $stream = $entry.Open()
        try { $stream.Write($readmeBytes, 0, $readmeBytes.Length) } finally { $stream.Dispose() }
        $hasher = [Security.Cryptography.SHA256]::Create()
        try { $readmeHash = ([BitConverter]::ToString($hasher.ComputeHash($readmeBytes))).Replace('-', '').ToLowerInvariant() } finally { $hasher.Dispose() }
        $records.Add([ordered]@{ path = 'README.txt'; bytes = $readmeBytes.Length; sha256 = $readmeHash })
        $manifest = [ordered]@{
            product = $ProductName
            version = $Version
            source_commit = $SourceCommit
            created_utc = [DateTime]::UtcNow.ToString('o')
            files = @($records.ToArray())
        }
        $manifestBytes = $encoding.GetBytes(($manifest | ConvertTo-Json -Depth 6))
        $entry = $archive.CreateEntry('sample-manifest.json')
        $stream = $entry.Open()
        try { $stream.Write($manifestBytes, 0, $manifestBytes.Length) } finally { $stream.Dispose() }
        $archive.Dispose()
        $archive = $null
        Move-Item -LiteralPath $temporary -Destination $archivePath -Force
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
        [IO.File]::WriteAllText($checksumPath, "$hash  $([IO.Path]::GetFileName($archivePath))`n", $encoding)
        Write-Host "Large Perfmon ZIP : $archivePath"
        Write-Host "Sample SHA-256    : $checksumPath"
    } finally {
        if ($null -ne $archive) { $archive.Dispose() }
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}
