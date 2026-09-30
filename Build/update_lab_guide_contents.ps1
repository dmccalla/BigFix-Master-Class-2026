# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

# Refresh the Contents field of the lab guide in Word and save it.
# Build/build_lab_guide.py runs this after writing the document.
param(
    [Parameter(Mandatory = $true)][string]$DocPath
)
$ErrorActionPreference = "Stop"
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
$d = $null
try {
    $d = $word.Documents.Open((Resolve-Path $DocPath).Path, $false, $false)
    $d.Windows.Item(1).View.Type = 3
    if ($d.TablesOfContents.Count -lt 1) { throw "the guide has no Contents field" }
    $d.TablesOfContents.Item(1).Update()
    $d.Repaginate()
    $d.Save()
    Write-Host ("Contents refreshed: {0} entries, {1} pages" -f $d.TablesOfContents.Item(1).Range.Paragraphs.Count, $d.ComputeStatistics(2))
}
finally {
    if ($null -ne $d) { $d.Close(0) }
    $word.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)
}
