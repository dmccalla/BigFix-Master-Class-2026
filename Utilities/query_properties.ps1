#!/usr/bin/env pwsh
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# Standalone utility: retain this notice when copying this file outside the repository.
# See the LICENSE and NOTICE files in the project root for license text and attribution.

# query_properties.ps1
# Reads the Agent Performance Counter XML captures and writes CSVs for loop
# data, the Top 10 slowest evaluations, and UDP notification results.
# Fast on big estates. Rows fold into per-lookup totals in one pass.
# The API is queried once per analysis, not once per property.
param(
    [Alias("LoopInputXml")]
    [string]$LoopXml = "",
    [Alias("UdpInputXml")]
    [string]$UdpXml = "",
    [Alias("InputFile")]
    [string]$Top10Input = "",
    [string]$ApiQueryUrl = "",
    [Alias("OutputCsv")]
    [string]$OutputTop10Csv = ".\top10-query-results.csv",
    [Alias("UdpOutputCsv")]
    [string]$OutputUdpCsv = ".\udp-notification-results.csv",
    [Alias("LoopOutputCsv")]
    [string]$OutputLoopCsv = "",
    [string]$BigFixUsername = "",
    [string]$BigFixPassword = "",
    [string]$LogFile = ".\top10_script_execution.log",
    [int]$TopCount = 10,
    [int]$TimeoutSec = 120,
    [int]$QueryAttempts = 2,
    # Capture mode. A single session-relevance query over the whole estate is
    # cut short by the server on a large deployment, and the truncation is
    # silent: the action still succeeds and the capture is simply short. These
    # run the same relevance in slices and append each slice to the capture,
    # which the answer scanner already accepts as concatenated documents.
    [string]$CaptureLoopXml = "",
    [string]$CaptureUdpXml = "",
    [string]$CaptureTop10Xml = "",
    [int]$BatchSize = 1000,
    # Extra relevance clause narrowing which computers are captured, for
    # example 'exists bes computer group whose (name of it = "Pilot")'. Left
    # empty the capture covers every computer.
    [string]$ComputerFilter = "",
    [switch]$IgnoreCertificateErrors,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Log($Message, $Level = "INFO") {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [$Level] $Message"
    if (-not $Quiet) { Write-Host $line }
    try { Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8 } catch { }
}

function Fail($Message) { Log $Message "ERROR"; exit 1 }

function Err($ErrorRecord) {
    $m = $ErrorRecord.Exception.Message
    if ($ErrorRecord.Exception.InnerException) { $m += " | " + $ErrorRecord.Exception.InnerException.Message }
    $m
}

function BigFixQueryErrorMessage($Xml) {
    $node = $Xml.BESAPI.Query.Error
    if ($null -eq $node) { return "" }
    if ($node -is [System.Xml.XmlElement]) {
        $message = $node.InnerText
    } else {
        $message = "$node"
    }
    if ([string]::IsNullOrWhiteSpace($message)) {
        try { $message = $node.OuterXml } catch { }
    }
    if ([string]::IsNullOrWhiteSpace($message)) {
        $message = "BigFix returned an unspecified query error."
    }
    $message.Trim()
}

# Matches one answer element. Capture files can hold several concatenated XML
# documents, so answers are scanned instead of DOM parsed.
$AnswerRegex = [regex]::new('<Answer\b[^>]*>(.*?)</Answer>', 'Singleline, Compiled')
# One top10 row. Example: 12.5: BES Support.123:Some Property
$Top10LineRegex = [regex]::new('^(?:\d+\s+\d+(?:\.\d+)?%\s+)?(?<sec>\d+(?:\.\d+)?):\s*(?<lookup>.+)$', 'Compiled')
# Splits a lookup into site, analysis id, and property.
$LookupRegex = [regex]::new('^(?<site>.+)\.(?<analysisId>\d+):(?<property>.+)$', 'Compiled')
# Splits a resolved property descriptor back into its fields.
$DescriptorRegex = [regex]::new('^Analysis Name=(?<an>.*) \| Display Name=(?<dn>.*) \| Name=(?<n>.*) \| Source Name=(?<sn>.*) \| Source ID=(?<sid>.*)$', 'Compiled')

# Returns every answer in the file. Falls back to plain text lines.
function ReadAnswers($Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return @() }
    if (-not (Test-Path -LiteralPath $Path)) { Fail "Input file is missing: $Path" }
    $raw = Get-Content -Raw -LiteralPath $Path -ErrorAction Stop
    if ($null -eq $raw) { return @() }
    $found = $AnswerRegex.Matches($raw)
    $out = New-Object System.Collections.Generic.List[string]
    if ($found.Count -gt 0) {
        foreach ($m in $found) { $out.Add(([System.Net.WebUtility]::HtmlDecode($m.Groups[1].Value)).Trim()) }
        return $out
    }
    foreach ($line in ($raw -split "`r?`n")) {
        $t = $line.Trim()
        if ($t.Length) { $out.Add($t) }
    }
    $out
}

# Computer names can contain commas. Extra leading fields merge back into the name.
function SplitAnswerFields($Line, $Expected) {
    $parts = @("$Line".Split(","))
    if ($parts.Count -le $Expected) { return $parts }
    $leadingCount = $parts.Count - $Expected + 1
    $merged = @((($parts | Select-Object -First $leadingCount) -join ",").Trim())
    $merged += @($parts | Select-Object -Skip $leadingCount)
    $merged
}

function JoinAnswerFieldSlice($Values, [int]$Start, [int]$End) {
    $items = New-Object System.Collections.Generic.List[string]
    for ($i = $Start; $i -le $End -and $i -lt $Values.Count; $i++) {
        if ($i -ge 0) { $items.Add("$($Values[$i])") }
    }
    (($items.ToArray()) -join ",").Trim()
}

function IsLoopMetricField($Value) {
    $text = "$Value".Trim()
    if (-not $text) { return $false }
    if ($text -match '^(?i:not reported|error)$') { return $true }
    if ($text -match '(?i)property does not exist|duplicates:|multiple results') { return $true }
    if ($text -match '^-?\d+(\.\d+)?$') { return $true }
    if ($text -match '^\d+:\d{1,2}(:\d{1,2}(\.\d+)?)?$') { return $true }
    return $false
}

function SplitLoopAnswerFields($Line) {
    $parts = @("$Line".Split(","))
    if ($parts.Count -le 7) {
        while ($parts.Count -lt 7) { $parts += "" }
        return $parts
    }

    $tailStart = $parts.Count - 3
    $middleEnd = $parts.Count - 4
    for ($i = 1; $i -lt $middleEnd; $i++) {
        if ((IsLoopMetricField $parts[$i]) -and (IsLoopMetricField $parts[$i + 1])) {
            return @(
                (JoinAnswerFieldSlice $parts 0 ($i - 1)),
                "$($parts[$i])".Trim(),
                "$($parts[$i + 1])".Trim(),
                (JoinAnswerFieldSlice $parts ($i + 2) $middleEnd),
                "$($parts[$tailStart])".Trim(),
                "$($parts[$tailStart + 1])".Trim(),
                "$($parts[$tailStart + 2])".Trim()
            )
        }
    }

    SplitAnswerFields $Line 7
}

function BuildLoopFromAnswers($Answers, $OutputPath) {
    if ([string]::IsNullOrWhiteSpace($OutputPath)) { return }
    $columns = @(
        "Computer Name",
        "Platform Health Check - Maximum Cycle Minutes",
        "Platform Health Check - Average Cycle Minutes",
        "Platform Health Check - Last UDP Ping",
        "Platform Health Check - Receiving UDP Pings",
        "Platform Health Check - Command Polling Enabled",
        "Platform Health Check - Command Polling Interval"
    )
    $loopRows = New-Object System.Collections.Generic.List[object]
    foreach ($answer in $Answers) {
        if (-not $answer) { continue }
        if ($answer -match '^\s*Computer Name\s*,') { continue }
        $parts = @(SplitLoopAnswerFields $answer)
        if ($parts.Count -lt 7) { continue }
        $loopRows.Add([pscustomobject]@{
            "Computer Name" = $parts[0].Trim()
            "Platform Health Check - Maximum Cycle Minutes" = $parts[1].Trim()
            "Platform Health Check - Average Cycle Minutes" = $parts[2].Trim()
            "Platform Health Check - Last UDP Ping" = $parts[3].Trim()
            "Platform Health Check - Receiving UDP Pings" = $parts[4].Trim()
            "Platform Health Check - Command Polling Enabled" = $parts[5].Trim()
            "Platform Health Check - Command Polling Interval" = $parts[6].Trim()
        })
    }
    if ($loopRows.Count) {
        $loopRows | Select-Object $columns | Export-Csv -LiteralPath $OutputPath -NoTypeInformation
        Log "Loop CSV written: $OutputPath ($($loopRows.Count) rows)"
    } else {
        ($columns -join ",") | Set-Content -LiteralPath $OutputPath -Encoding UTF8
        Log "Loop CSV written (header-only): $OutputPath"
    }
}

function IsUdpAnswer($Line) {
    $parts = @(SplitAnswerFields $Line 4)
    if ($parts.Count -lt 4) { return $false }
    return "$($parts[3])".Trim() -match '^(?i:true|false|yes|no|not reported|platform health check - receiving udp pings\b|receiving udp pings\b)'
}

function BuildUdpFromAnswers($Answers, $OutputPath) {
    $columns = @("Computer Name", "IPv4 Addresses", "Relay", "Platform Health Check - Receiving UDP Pings")
    $udpRows = New-Object System.Collections.Generic.List[object]
    foreach ($answer in $Answers) {
        if (-not $answer) { continue }
        if ($answer -match '^\s*Computer Name\s*,') { continue }
        $parts = @(SplitAnswerFields $answer 4)
        if ($parts.Count -lt 4) { continue }
        if (-not (IsUdpAnswer $answer)) { continue }
        $udpRows.Add([pscustomobject]@{
            "Computer Name" = $parts[0].Trim()
            "IPv4 Addresses" = $parts[1].Trim()
            "Relay" = $parts[2].Trim()
            "Platform Health Check - Receiving UDP Pings" = $parts[3].Trim()
        })
    }
    if ($udpRows.Count) {
        $udpRows | Select-Object $columns | Export-Csv -LiteralPath $OutputPath -NoTypeInformation
        Log "UDP notification CSV written: $OutputPath ($($udpRows.Count) rows)"
    } else {
        ($columns -join ",") | Set-Content -LiteralPath $OutputPath -Encoding UTF8
        Log "UDP CSV written (header-only): $OutputPath"
    }
}

# One query returns every property of the analysis, in the same text format
# the old per property query used, so the CSV Result strings are unchanged.
function AnalysisRelevance($Site, $AnalysisId) {
    '("Analysis Name=" & name of source analysis of it & " | Display Name=" & display name of it & " | Name=" & name of it & " | Source Name=" & source name of it & " | Source ID=" & (source id of it as string)) of bes properties whose (name of site of source analysis of it = "' + $Site + '" and id of source analysis of it = ' + $AnalysisId + ')'
}

# API setup, done once and only when something actually needs the API.
$script:ApiReady = $false
function EnsureApiReady($Purpose) {
    if ($script:ApiReady) { return }
    if ([string]::IsNullOrWhiteSpace($ApiQueryUrl)) { Fail "ApiQueryUrl is required for $Purpose" }
    if ([string]::IsNullOrWhiteSpace($BigFixUsername) -or [string]::IsNullOrWhiteSpace($BigFixPassword)) { Fail "BigFix credentials were not supplied." }
    $script:ApiQueryUrl = $ApiQueryUrl.Trim().TrimEnd("/")
    if ($script:ApiQueryUrl -notmatch "/api/query$") {
        if ($script:ApiQueryUrl -match "/api$") { $script:ApiQueryUrl += "/query" } else { $script:ApiQueryUrl += "/api/query" }
    }
    $auth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes(("{0}:{1}" -f $BigFixUsername, $BigFixPassword)))
    $script:Headers = @{ Authorization = "Basic $auth"; Accept = "application/xml" }
    if ($IgnoreCertificateErrors) {
        if (-not ("BigFixTrustAll" -as [type])) {
            Add-Type "using System.Net; public static class BigFixTrustAll { public static void Enable() { ServicePointManager.ServerCertificateValidationCallback = delegate { return true; }; } }"
        }
        [BigFixTrustAll]::Enable()
        Log "Certificate validation bypass enabled." "WARN"
    }
    $script:ApiReady = $true
}

# Raw response body, so a capture keeps the server's own XML rather than a
# re-serialised copy. Errors are raised, never written to the capture: a
# truncated or failed query must not look like a short estate.
function InvokeBigFixQueryRaw($Relevance, $Purpose = "BigFix API query") {
    $url = $script:ApiQueryUrl + "?relevance=" + [Uri]::EscapeDataString($Relevance)
    $attempt = 0
    while ($attempt -lt $QueryAttempts) {
        $attempt++
        try {
            $response = Invoke-WebRequest -Uri $url -Headers $script:Headers -UseBasicParsing -TimeoutSec $TimeoutSec
            $content = $response.Content
            [xml]$xml = $content
            $queryError = BigFixQueryErrorMessage $xml
            if ($queryError) { throw "BigFix query error: $queryError" }
            return [pscustomobject]@{
                Content = $content
                Count   = @($xml.BESAPI.Query.Result.Answer | Where-Object { $null -ne $_ }).Count
            }
        } catch {
            $detail = Err $_
            if ($attempt -ge $QueryAttempts) {
                throw "$Purpose failed after $attempt attempt(s). Details: $detail"
            }
            Log "$Purpose failed on attempt $attempt/$QueryAttempts. Retrying. Details: $detail" "WARN"
            Start-Sleep -Seconds $attempt
        }
    }
}

function ComputerSetRelevance($Filter) {
    if ([string]::IsNullOrWhiteSpace($Filter)) { return "set of BES computers" }
    "set of BES computers whose ($Filter)"
}

# Slice boundaries taken from the real ids rather than a fixed stride, so every
# batch holds BatchSize computers however sparsely the ids are allocated.
function GetComputerIdBatches($Filter, $Size) {
    $setRel = ComputerSetRelevance $Filter
    $idRel = "(id of it as string) of elements of $setRel"
    $ids = @(InvokeBigFixQuery $idRel | ForEach-Object { [int64]$_ } | Sort-Object)
    if (-not $ids.Count) { return @() }
    Log "Computers in scope: $($ids.Count)"
    $batches = New-Object System.Collections.Generic.List[object]
    for ($i = 0; $i -lt $ids.Count; $i += $Size) {
        $last = [Math]::Min($i + $Size, $ids.Count) - 1
        $batchIds = @($ids[$i..$last])
        $batches.Add([pscustomobject]@{
            Low      = $ids[$i]
            High     = $ids[$last]
            Expected = $last - $i + 1
            Ids      = $batchIds
        })
    }
    $batches
}

function NewComputerIdBatch($Ids) {
    $items = @($Ids)
    [pscustomobject]@{
        Low      = $items[0]
        High     = $items[$items.Count - 1]
        Expected = $items.Count
        Ids      = $items
    }
}

# A failed or silently short response is retried in smaller slices. This keeps
# large deployments moving while still failing with the exact computer id and
# BigFix error when one endpoint cannot be queried safely.
function CaptureBatchWithFallback($Template, $OutputPath, $Label, $Filter, $Batch, $BatchName, [bool]$RequireFullCount) {
    $scope = "id of it >= $($Batch.Low) and id of it <= $($Batch.High)"
    if (-not [string]::IsNullOrWhiteSpace($Filter)) { $scope = "($Filter) and $scope" }
    $rel = $Template.Replace("COMPUTERSET", "set of BES computers whose ($scope)")
    try {
        $result = InvokeBigFixQueryRaw $rel "$Label batch $BatchName"
        if ($RequireFullCount -and $result.Count -lt $Batch.Expected) {
            throw "Short response: $($result.Count) answers for $($Batch.Expected) computers."
        }
        Add-Content -LiteralPath $OutputPath -Value $result.Content -Encoding UTF8
        Log "$Label batch $($BatchName): ids $($Batch.Low)-$($Batch.High), $($result.Count) answers"
        return [int]$result.Count
    } catch {
        $detail = Err $_
        if ($Batch.Expected -le 1) {
            throw "$Label batch $BatchName failed for computer id $($Batch.Low). Details: $detail"
        }
        $split = [int][Math]::Floor($Batch.Ids.Count / 2)
        $leftIds = @($Batch.Ids[0..($split - 1)])
        $rightIds = @($Batch.Ids[$split..($Batch.Ids.Count - 1)])
        Log "$Label batch $BatchName failed for ids $($Batch.Low)-$($Batch.High). Retrying as two smaller batches. Details: $detail" "WARN"
        $left = NewComputerIdBatch $leftIds
        $right = NewComputerIdBatch $rightIds
        $leftCount = CaptureBatchWithFallback $Template $OutputPath $Label $Filter $left "$BatchName.a" $RequireFullCount
        $rightCount = CaptureBatchWithFallback $Template $OutputPath $Label $Filter $right "$BatchName.b" $RequireFullCount
        return [int]$leftCount + [int]$rightCount
    }
}

# Runs one relevance template per batch and appends each response to the
# capture. The template must contain the COMPUTERSET token where the computer
# set belongs.
function CaptureBatched($Template, $OutputPath, $Label, $Filter, $Size) {
    EnsureApiReady "capturing $Label"
    $batches = @(GetComputerIdBatches $Filter $Size)
    if (-not $batches.Count) { Fail "No computers in scope for $Label. Check the ComputerFilter." }
    Remove-Item -LiteralPath $OutputPath -ErrorAction SilentlyContinue
    $expected = ($batches | Measure-Object -Property Expected -Sum).Sum
    $captured = 0
    $index = 0
    foreach ($b in $batches) {
        $index++
        $captured += CaptureBatchWithFallback $Template $OutputPath $Label $Filter $b "$index/$($batches.Count)" $true
    }
    # The whole point of the exercise. A short capture is reported, not shipped.
    if ($captured -lt $expected) {
        Fail "$Label capture is short: $captured answers for $expected computers. Lower -BatchSize and run again."
    }
    Log "$Label capture complete: $captured answers for $expected computers -> $OutputPath"
    $captured
}

function InvokeBigFixQuery($Relevance) {
    $url = $ApiQueryUrl + "?relevance=" + [Uri]::EscapeDataString($Relevance)
    Log "Request URL: $url"
    $response = InvokeBigFixQueryRaw $Relevance "BigFix API query"
    [xml]$xml = $response.Content
    # A zero-answer Result yields $null, and $null through a pipeline is one
    # iteration, not none. Without this filter an empty result reads as a
    # single blank row: a phantom computer id of 0, or a descriptor that
    # "did not parse".
    @($xml.BESAPI.Query.Result.Answer | Where-Object { $null -ne $_ } | ForEach-Object { $_.InnerText })
}

# --- Main ------------------------------------------------------------------

try {
    "BigFix single-input query started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Set-Content -LiteralPath $LogFile -Encoding UTF8
} catch {
    if (-not $Quiet) { Write-Host "ERROR: Cannot write log file: $LogFile" }
    exit 1
}
if ($QueryAttempts -lt 1) { $QueryAttempts = 1 }

# --- Capture ---------------------------------------------------------------
# Same relevance the task used to run through a single iem call, with the
# computer set factored out so it can be sliced. COMPUTERSET is substituted per
# batch.
$LoopTemplate = @'
(item 0 of it & "," & item 1 of it & "," & item 2 of it & "," & item 3 of it & "," & item 4 of it & "," & item 5 of it & "," & item 6 of it)
of (item 0 of it, item 1 of it, item 2 of it, item 3 of it, item 4 of it, item 5 of it, item 6 of it)
of
(
  (
    (if exists name of item 0 of it then name of item 0 of it else "Computer ID " & (id of item 0 of it as string)),
    (if (size of item 1 of it = 1) then ((if it = "" then "Not Reported" else it) of concatenation ";" of values of results (item 0 of it, elements of item 1 of it)) else (if (size of item 1 of it > 1) then (("Platform Health Check - Maximum Cycle Minutes Duplicates: " & concatenation "|" of ((name of it) & "=" & (id of it as string)) of elements of item 1 of it) as string) else ("Platform Health Check - Maximum Cycle Minutes Property Does Not Exist"))),
    (if (size of item 2 of it = 1) then ((if it = "" then "Not Reported" else it) of concatenation ";" of values of results (item 0 of it, elements of item 2 of it)) else (if (size of item 2 of it > 1) then (("Platform Health Check - Average Cycle Minutes Duplicates: " & concatenation "|" of ((name of it) & "=" & (id of it as string)) of elements of item 2 of it) as string) else ("Platform Health Check - Average Cycle Minutes Property Does Not Exist"))),
    (if (size of item 3 of it = 1) then ((if it = "" then "Not Reported" else it) of concatenation ";" of values of results (item 0 of it, elements of item 3 of it)) else (if (size of item 3 of it > 1) then (("Platform Health Check - Last UDP Ping Duplicates: " & concatenation "|" of ((name of it) & "=" & (id of it as string)) of elements of item 3 of it) as string) else ("Platform Health Check - Last UDP Ping Property Does Not Exist"))),
    (if (size of item 4 of it = 1) then ((if it = "" then "Not Reported" else it) of concatenation ";" of values of results (item 0 of it, elements of item 4 of it)) else (if (size of item 4 of it > 1) then (("Platform Health Check - Receiving UDP Pings Duplicates: " & concatenation "|" of ((name of it) & "=" & (id of it as string)) of elements of item 4 of it) as string) else ("Platform Health Check - Receiving UDP Pings Property Does Not Exist"))),
    (if (size of item 5 of it = 1) then ((if it = "" then "Not Set" else it) of concatenation ";" of values of results (item 0 of it, elements of item 5 of it)) else (if (size of item 5 of it > 1) then (("Platform Health Check - Command Polling Enabled Duplicates: " & concatenation "|" of ((name of it) & "=" & (id of it as string)) of elements of item 5 of it) as string) else ("Platform Health Check - Command Polling Enabled Property Does Not Exist"))),
    (if (size of item 6 of it = 1) then ((if it = "" then "Not Set" else it) of concatenation ";" of values of results (item 0 of it, elements of item 6 of it)) else (if (size of item 6 of it > 1) then (("Platform Health Check - Command Polling Interval Duplicates: " & concatenation "|" of ((name of it) & "=" & (id of it as string)) of elements of item 6 of it) as string) else ("Platform Health Check - Command Polling Interval Property Does Not Exist")))
  )
  of (elements of item 0 of it, item 1 of it, item 2 of it, item 3 of it, item 4 of it, item 5 of it, item 6 of it)
)
of
(
  COMPUTERSET,
  set of bes properties whose (name of it as lowercase = ("Platform Health Check - Maximum Cycle Minutes") as lowercase),
  set of bes properties whose (name of it as lowercase = ("Platform Health Check - Average Cycle Minutes") as lowercase),
  set of bes properties whose (name of it as lowercase = ("Platform Health Check - Last UDP Ping") as lowercase),
  set of bes properties whose (name of it as lowercase = ("Platform Health Check - Receiving UDP Pings") as lowercase),
  set of bes properties whose (name of it as lowercase = ("Platform Health Check - Command Polling Enabled") as lowercase or name of it as lowercase = ("Platform Health Check - Command Polling Enbaled") as lowercase),
  set of bes properties whose (name of it as lowercase = ("Platform Health Check - Command Polling Interval") as lowercase)
)
'@
$LoopTemplate = ($LoopTemplate -replace '\s+', ' ').Trim()

$UdpTemplate = '(item 0 of it & ", " & item 1 of it & ", " & item 2 of it & ", " & item 3 of it) of (item 0 of it, item 1 of it, item 2 of it, item 3 of it) of (((if exists name of item 0 of it then name of item 0 of it else "Computer ID " & (id of item 0 of it as string)),(if (size of item 1 of it = 1) then ((if it = "" then "Not Reported" else it) of concatenation ";" of values of results (item 0 of it, elements of item 1 of it)) else (if (size of item 1 of it > 1) then (("IP Address Duplicates: " & concatenation "|" of ((name of it) & "=" & (id of it as string)) of elements of item 1 of it) as string) else ("IP Address Property Does Not Exist"))),(if (size of item 2 of it = 1) then ((if it = "" then "Not Reported" else it) of concatenation ";" of values of results (item 0 of it, elements of item 2 of it)) else (if (size of item 2 of it > 1) then (("Relay Duplicates: " & concatenation "|" of ((name of it) & "=" & (id of it as string)) of elements of item 2 of it) as string) else ("Relay Property Does Not Exist"))),(if (size of item 3 of it = 1) then ((if it = "" then "Not Reported" else it) of concatenation ";" of values of results (item 0 of it, elements of item 3 of it)) else (if (size of item 3 of it > 1) then (("Platform Health Check - Receiving UDP Pings Duplicates: " & concatenation "|" of ((name of it) & "=" & (id of it as string)) of elements of item 3 of it) as string) else ("Platform Health Check - Receiving UDP Pings Property Does Not Exist")))) of (elements of item 0 of it, item 1 of it, item 2 of it, item 3 of it)) of (COMPUTERSET, set of bes properties whose (reserved flag of it AND name of it as lowercase = ("IP Address") as lowercase), set of bes properties whose (name of it as lowercase = ("Relay") as lowercase), set of bes properties whose (name of it as lowercase = ("Platform Health Check - Receiving UDP Pings") as lowercase))'

# The original Top 10 query had no computer set at all, so it could not be
# sliced and had no expected count to check against. Scoping it by computer
# gives it both.
$Top10Template = 'values of results (elements of COMPUTERSET, bes property whose (name of it = "Platform Health Check - Top 10 Slow Evaluations"))'

if (-not [string]::IsNullOrWhiteSpace($CaptureLoopXml)) {
    [void](CaptureBatched $LoopTemplate $CaptureLoopXml "Loop times" $ComputerFilter $BatchSize)
    $LoopXml = $CaptureLoopXml
}
if (-not [string]::IsNullOrWhiteSpace($CaptureUdpXml)) {
    [void](CaptureBatched $UdpTemplate $CaptureUdpXml "UDP notification" $ComputerFilter $BatchSize)
    $UdpXml = $CaptureUdpXml
}
if (-not [string]::IsNullOrWhiteSpace($CaptureTop10Xml)) {
    # Not every computer reports this property, so a short answer count here is
    # expected rather than a failure. Reported for visibility only.
    EnsureApiReady "capturing Top 10"
    $batches = @(GetComputerIdBatches $ComputerFilter $BatchSize)
    Remove-Item -LiteralPath $CaptureTop10Xml -ErrorAction SilentlyContinue
    $t10 = 0
    $n = 0
    foreach ($b in $batches) {
        $n++
        $t10 += CaptureBatchWithFallback $Top10Template $CaptureTop10Xml "Top 10" $ComputerFilter $b "$n/$($batches.Count)" $false
    }
    Log "Top 10 capture complete: $t10 answers from $($batches.Count) batches -> $CaptureTop10Xml"
    $Top10Input = $CaptureTop10Xml
}

if (-not (Test-Path -LiteralPath $LoopXml)) { Fail "Loop XML input is missing: $LoopXml" }
$top10Source = if ([string]::IsNullOrWhiteSpace($Top10Input)) { $LoopXml } else { $Top10Input }

# Loop CSV.
if (-not [string]::IsNullOrWhiteSpace($OutputLoopCsv)) {
    $loopAnswers = ReadAnswers $LoopXml
    Log "Collected $($loopAnswers.Count) loop answers from $LoopXml"
    BuildLoopFromAnswers $loopAnswers $OutputLoopCsv
}

# UDP CSV.
if ([string]::IsNullOrWhiteSpace($UdpXml)) {
    Log "UDP XML input omitted; writing header-only UDP CSV" "WARN"
    BuildUdpFromAnswers @() $OutputUdpCsv
} else {
    $udpAnswers = ReadAnswers $UdpXml
    Log "Collected $($udpAnswers.Count) UDP notification answers from $UdpXml"
    BuildUdpFromAnswers $udpAnswers $OutputUdpCsv
}

# One pass over the top10 rows. Each row updates count, total, and max for
# its lookup. No row objects, no grouping, no sorting of raw rows.
$agg = New-Object 'System.Collections.Generic.Dictionary[string,object]'
$rowsSeen = 0
foreach ($answer in (ReadAnswers $top10Source)) {
    $m = $Top10LineRegex.Match("$answer".Trim().Trim([char]0xFEFF).Trim('"'))
    if (-not $m.Success) { continue }
    $rowsSeen++
    $lookup = $m.Groups['lookup'].Value.Trim()
    $sec = 0.0
    [void][double]::TryParse($m.Groups['sec'].Value, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$sec)
    $stats = $null
    if ($agg.TryGetValue($lookup, [ref]$stats)) {
        $stats[0]++
        $stats[1] += $sec
        if ($sec -gt $stats[2]) { $stats[2] = $sec }
    } else {
        $agg[$lookup] = [double[]]@(1, $sec, $sec)
    }
}
Log "Aggregated $rowsSeen top10 rows into $($agg.Count) distinct lookups from $top10Source"

$topColumns = @("Occurrences", "AvgClientProcessingSeconds", "TotalClientProcessingSeconds", "MaxClientProcessingSeconds", "Status", "Result")
if ($agg.Count -eq 0) {
    Log "No Top10 rows found in input; writing header-only Top10 CSV"
    ($topColumns -join ",") | Set-Content -LiteralPath $OutputTop10Csv -Encoding UTF8
    exit 0
}
if ($TopCount -le 0) { $TopCount = 10 }

# Classify each distinct lookup. Background rows resolve locally.
$candidates = New-Object System.Collections.Generic.List[object]
foreach ($entry in $agg.GetEnumerator()) {
    $stats = $entry.Value
    $c = [pscustomobject]@{
        Lookup = $entry.Key; Site = ""; AnalysisId = 0; Property = ""
        NeedsLookup = $false; Status = "OK"; Result = ""
        Occurrences = [int]$stats[0]
        AvgClientProcessingSeconds = $stats[1] / $stats[0]
        TotalClientProcessingSeconds = $stats[1]
        MaxClientProcessingSeconds = $stats[2]
    }
    $m = $LookupRegex.Match($entry.Key)
    if (-not $m.Success) {
        $c.Status = "PARSE FAILED"
        $c.Result = "Expected lookup format: Site Name.AnalysisId:Property Name"
    } else {
        $c.Site = $m.Groups['site'].Value.Trim()
        $c.AnalysisId = [int]$m.Groups['analysisId'].Value
        $c.Property = $m.Groups['property'].Value.Trim()
        if ($c.Property -eq "Background Evaluation") {
            if ($c.Site -match '^CustomSite_(.+)$') { $c.Result = "Background Evaluation of Custom Site: $($matches[1])" }
            else { $c.Result = "Background Evaluation of External Site: $($c.Site)" }
        } else {
            $c.NeedsLookup = $true
        }
    }
    $candidates.Add($c)
}
Log "Prepared candidate groups: $($candidates.Count)"

if (@($candidates | Where-Object { $_.NeedsLookup }).Count -gt 0) {
    EnsureApiReady "resolving Top10 lookups"
}

# One API query per distinct analysis. Index every returned descriptor by
# display name, name, source name, and source id. The dictionary is case
# sensitive to match relevance equality.
$analysisIndex = New-Object 'System.Collections.Generic.Dictionary[string,object]'
$analysisError = New-Object 'System.Collections.Generic.Dictionary[string,string]'
foreach ($c in $candidates) {
    if (-not $c.NeedsLookup) { continue }
    # Id first: the id is numeric, so the first pipe is always the separator.
    $key = "$($c.AnalysisId)|$($c.Site)"
    if ($analysisIndex.ContainsKey($key) -or $analysisError.ContainsKey($key)) { continue }
    try {
        $rows = @(InvokeBigFixQuery (AnalysisRelevance $c.Site $c.AnalysisId))
        $index = New-Object 'System.Collections.Generic.Dictionary[string,object]'
        foreach ($row in $rows) {
            $d = $DescriptorRegex.Match("$row")
            if (-not $d.Success) { Log "Descriptor did not parse: $row" "WARN"; continue }
            $keys = @(("D|" + $d.Groups['dn'].Value), ("N|" + $d.Groups['n'].Value), ("S|" + $d.Groups['sn'].Value))
            $sid = [int64]0
            if ([int64]::TryParse($d.Groups['sid'].Value.Trim(), [ref]$sid)) { $keys += ("I|" + $sid) }
            foreach ($k in $keys) {
                if (-not $index.ContainsKey($k)) { $index[$k] = New-Object System.Collections.Generic.List[string] }
                $index[$k].Add("$row")
            }
        }
        $analysisIndex[$key] = $index
        Log "Fetched $($rows.Count) property descriptors for $($c.Site) analysis $($c.AnalysisId)"
    } catch {
        $analysisError[$key] = Err $_
        Log "Analysis query failed for $($c.Site) analysis $($c.AnalysisId): $($analysisError[$key])" "WARN"
    }
}

# Resolve every lookup locally. A lookup matches on display name, name,
# source name, or trailing digits as source id. Same rule as the old
# per property relevance. Prop 007 matches source id 7.
foreach ($c in $candidates) {
    if (-not $c.NeedsLookup) { continue }
    $key = "$($c.AnalysisId)|$($c.Site)"
    if ($analysisError.ContainsKey($key)) {
        $c.Status = "ERROR"
        $c.Result = $analysisError[$key]
        continue
    }
    $index = $analysisIndex[$key]
    $keys = @(("D|" + $c.Property), ("N|" + $c.Property), ("S|" + $c.Property))
    $sid = [int64]0
    if ($c.Property -match '(\d+)$' -and [int64]::TryParse($matches[1], [ref]$sid)) { $keys += ("I|" + $sid) }
    $seenRows = New-Object 'System.Collections.Generic.HashSet[string]'
    $answers = New-Object System.Collections.Generic.List[string]
    foreach ($k in $keys) {
        $bucket = $null
        if ($index.TryGetValue($k, [ref]$bucket)) {
            foreach ($row in $bucket) { if ($seenRows.Add($row)) { $answers.Add($row) } }
        }
    }
    if ($answers.Count) { $c.Status = "OK"; $c.Result = ($answers -join " ; ") }
    else { $c.Status = "NO RESULTS"; $c.Result = $c.Lookup }
}

# Group by resolved name. Lookups resolving to the same name merge with
# exact combined stats.
$groups = New-Object 'System.Collections.Generic.Dictionary[string,object]'
foreach ($c in $candidates) {
    $g = $null
    if (-not $groups.TryGetValue($c.Result, [ref]$g)) {
        $g = @{ Occurrences = 0; Total = 0.0; Max = 0.0; Statuses = New-Object 'System.Collections.Generic.HashSet[string]' }
        $groups[$c.Result] = $g
    }
    $g.Occurrences += $c.Occurrences
    $g.Total += $c.TotalClientProcessingSeconds
    if ($c.MaxClientProcessingSeconds -gt $g.Max) { $g.Max = $c.MaxClientProcessingSeconds }
    [void]$g.Statuses.Add($c.Status)
}

$report = New-Object System.Collections.Generic.List[object]
foreach ($entry in $groups.GetEnumerator()) {
    $g = $entry.Value
    $report.Add([pscustomobject]@{
        Occurrences = [int]$g.Occurrences
        AvgClientProcessingSeconds = [math]::Round($g.Total / $g.Occurrences, 3)
        TotalClientProcessingSeconds = [math]::Round($g.Total, 3)
        MaxClientProcessingSeconds = [math]::Round($g.Max, 3)
        Status = (@($g.Statuses | Sort-Object) -join " ; ")
        Result = $entry.Key
        SortSeconds = $g.Total / $g.Occurrences
    })
}

# Slowest average first. Ties break on total, then occurrences, then name.
$report = @($report | Sort-Object @{e={$_.SortSeconds};d=$true}, @{e={$_.TotalClientProcessingSeconds};d=$true}, @{e={$_.Occurrences};d=$true}, Result | Select-Object -First $TopCount)
if ($report.Count) {
    $report | Select-Object $topColumns | Export-Csv -LiteralPath $OutputTop10Csv -NoTypeInformation
} else {
    ($topColumns -join ",") | Set-Content -LiteralPath $OutputTop10Csv -Encoding UTF8
}

$ok = @($candidates | Where-Object { $_.Status -eq "OK" }).Count
$none = @($candidates | Where-Object { $_.Status -eq "NO RESULTS" }).Count
$err = @($candidates | Where-Object { $_.Status -eq "ERROR" }).Count
$parse = @($candidates | Where-Object { $_.Status -eq "PARSE FAILED" }).Count
Log "Query run finished. OK=$ok; No Results=$none; Errors=$err; Parse Failed=$parse"
Log "Top10 Result CSV: $OutputTop10Csv"

# Exit 2 means some rows failed. The CSV is still written.
if ($err -gt 0 -or $parse -gt 0) { exit 2 }
exit 0
