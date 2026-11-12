# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
# ------------------------------------------------------------------------------
# WHY THIS SCRIPT EXISTS
# This helper runs ONE BigFix IEM CLI request for the Deployment Information
# task, saves the answer, and records whether the request worked.
#
# BigFix ActionScript can start a program and read its exit code. It cannot
# read an HTTP status, check that an XML answer is complete, time a request, or
# remember anything between the 184 separate requests this task makes. Without
# those four things the task cannot tell a failed request from an empty answer.
# It would keep sending requests to a server that is refusing the login or is
# down, and the capture could look complete when it is not. Before this helper
# each query was a single cmd.exe line with no check of the result.
#
# WHAT IT DOES NOT DO
# - It makes no network connection of its own. It only starts the local IEM CLI
#   whose path the task passes in with -IemPath.
# - It never receives the user name or password. The task logs in with iem login.
# - It does not download, install or run any other code.
# - It does not change the queries. The task passes each relevance query in
#   unchanged and a test locks all 182 of them by hash.
# - It does not change system settings. It writes only the capture file, the
#   diagnostics files next to -StateFile, and one temporary response file that
#   it deletes.
#
# SAFEGUARDS
# - XML answers are parsed with DTD processing prohibited and no resolver.
# - Hardware facts come from a short allowlist of CIM properties with a 3
#   second timeout. A failure there is noted and never stops the collection.
# - Raw CLI output, arguments and exception text are never written to the
#   diagnostics files.
#
# HOW TO REVIEW IT
# - This text is identical to Tasks and Analyses/Support/DeploymentApiRequest.ps1.
#   A test requires the copy embedded in the task to match that file exactly.
# - The SHA-256 of this script is written to the summary of every run.
#
# MODES (the task calls this script four ways)
#   Init     Create the diagnostics files and record the start. No request.
#   Login    Record whether iem login worked. Exit 24001 if it did not.
#   Request  Run one query or resource, append the answer, classify the result.
#   Finish   Mark the run Completed or Incomplete and write the final summary.
#
# EXIT CODES (returned to BigFix so the action shows the real result)
#   0      Everything worked.
#   24001  Login failed. No query was sent.
#   24002  The server answered 401 (authentication failed). Stopped at once.
#   24003  Three availability failures in a row. Stopped to avoid piling on.
#   24004  Finished, but at least one query failed. The capture is incomplete.
#   24005  This helper itself failed (for example it could not write a file).
# ------------------------------------------------------------------------------
param(
    [ValidateSet('Init','Login','Request','Finish')][string]$Mode,
    [string]$IemPath,
    [string]$Resource,
    [string]$EncodedRelevance,
    [string]$Capture,
    [string]$StateFile,
    [string]$CsvFile,
    [int]$QueryNumber = 0,
    [int]$NativeExitCode = 0,
    [string]$SelectedSections = '',
    [ValidateRange(-1,300)][int]$PauseSeconds = -1,
    [ValidateSet('0','1','Unknown')][string]$DataLogs = 'Unknown',
    [ValidateSet('Standalone','Day1')][string]$TaskType = 'Standalone',
    [string]$OtherModules = '',
    [string]$ClientVersion = ''
)
# Stop on any error. An unexpected problem is then reported with exit code
# 24005 instead of being ignored.
$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
# LOCAL CONTEXT. Reads the hardware of the machine this task runs on (the
# root server) so the summary can say what the collection ran on. It is
# used for the diagnostics summary only. It is not part of the collected data.
# Environment discovery is local only. Copy an allowlist, never entire CIM objects.
function Get-LocalContext {
    $hardware = [ordered]@{
        Manufacturer = $null; Model = $null; CpuModel = $null; CpuSockets = $null
        CpuCores = $null; LogicalProcessors = $null; OsReportedMemoryGiB = $null
        OsCaption = $null; OsVersion = $null; OsArchitecture = $null
    }
    $warnings = @()
    try {
        $computer = Get-CimInstance -ClassName Win32_ComputerSystem -Property Manufacturer,Model,TotalPhysicalMemory -OperationTimeoutSec 3 -ErrorAction Stop
        if ($null -ne $computer) {
            $hardware.Manufacturer = Limit-ContextText $computer.Manufacturer
            $hardware.Model = Limit-ContextText $computer.Model
            if ($computer.TotalPhysicalMemory -gt 0) { $hardware.OsReportedMemoryGiB = [Math]::Round($computer.TotalPhysicalMemory / 1GB, 2) }
        } else { $warnings += 'Local computer hardware unavailable.' }
    } catch { $warnings += 'Local computer hardware unavailable.' }
    try {
        $processors = @(Get-CimInstance -ClassName Win32_Processor -Property Name,NumberOfCores,NumberOfLogicalProcessors -OperationTimeoutSec 3 -ErrorAction Stop)
        if ($processors.Count -gt 0) {
            $hardware.CpuModel = Limit-ContextText (($processors | ForEach-Object { $_.Name } | Sort-Object -Unique) -join ', ')
            $hardware.CpuSockets = $processors.Count
            $cores = ($processors | Measure-Object NumberOfCores -Sum).Sum
            $logical = ($processors | Measure-Object NumberOfLogicalProcessors -Sum).Sum
            if ($cores -gt 0) { $hardware.CpuCores = $cores }
            if ($logical -gt 0) { $hardware.LogicalProcessors = $logical }
        } else { $warnings += 'Local processor details unavailable.' }
    } catch { $warnings += 'Local processor details unavailable.' }
    try {
        $os = Get-CimInstance -ClassName Win32_OperatingSystem -Property Caption,Version,OSArchitecture -OperationTimeoutSec 3 -ErrorAction Stop
        if ($null -ne $os) {
            $hardware.OsCaption = Limit-ContextText $os.Caption
            $hardware.OsVersion = Limit-ContextText $os.Version
            $hardware.OsArchitecture = Limit-ContextText $os.OSArchitecture
        } else { $warnings += 'Local operating system details unavailable.' }
    } catch { $warnings += 'Local operating system details unavailable.' }
    return [pscustomobject]@{
        LocalRootHardware = [pscustomobject]$hardware
        DiscoveryWarnings = $warnings
        Deployment = [pscustomobject][ordered]@{
            ComputerCount = $null; ActiveComputerCount = $null; RelayCount = $null
            ServerVersionCounts = $null; RootServersReportedCpu = $null
            RootServersReportedRam = $null; RootServersReportedOs = $null
        }
        Sources = [pscustomobject]@{}
    }
}
# Removes control characters and caps text at 512 characters before it is
# written to the diagnostics.
function Limit-ContextText($value) {
    if ($null -eq $value) { return $null }
    $clean = ([string]$value -replace '[\x00-\x1f\x7f]', ' ').Trim()
    if ($clean.Length -gt 512) { $clean = $clean.Substring(0, 512) + ' [truncated]' }
    return $clean
}
# Shows 'Unavailable' instead of a blank so a missing value is never read as zero.
function Format-Known($value) {
    if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) { return 'Unavailable' }
    return [string]$value
}
# Turns milliseconds into hh:mm:ss text for the summary.
function Format-Duration($milliseconds) {
    return [TimeSpan]::FromMilliseconds([Math]::Max(0, [double]$milliseconds)).ToString('c')
}
# Reads the evaluation time the server reports (for example 12 ms or 1.5 s)
# and converts it to milliseconds. Returns nothing if the text is not a time.
function Convert-EvaluationMs($value) {
    $match = [regex]::Match([string]$value, '^\s*(\d+(?:\.\d+)?)\s*(ms|s|us|milliseconds?|seconds?)\s*$', 'IgnoreCase,CultureInvariant')
    if (-not $match.Success) { return $null }
    $number = [double]::Parse($match.Groups[1].Value, [Globalization.CultureInfo]::InvariantCulture)
    $unit = $match.Groups[2].Value.ToLowerInvariant()
    if ($unit -eq 'us') { return $number / 1000 }
    if ($unit -eq 's' -or $unit.StartsWith('second')) { return $number * 1000 }
    return $number
}
# RUN RECORD. Created once at Init. Holds the start time, the sections the
# operator selected, how many requests are planned, and the SHA-256 of this
# script and of the query list so a reviewer can tie a run to the exact code.
function New-RunContext {
    # Counts are verified against the unchanged task requests by offline contracts.
    $counts = [ordered]@{ General = 30; Root = 8; Relays = 25; RelayAffiliation = 3; Clients = 21; ClientSettings = 17; Operators = 19; Content = 28; Properties = 12; Actions = 19 }
    $selected = @()
    foreach ($item in $SelectedSections.Split(';')) {
        $pair = $item.Split('=')
        if ($pair.Count -eq 2 -and $counts.Contains($pair[0]) -and $pair[1] -eq 'true') { $selected += $pair[0] }
    }
    $planned = 0
    foreach ($section in $selected) { $planned += $counts[$section] }
    if ($selected -contains 'General') { $planned += 2 }
    $otherSelected = @()
    foreach ($item in $OtherModules.Split(';')) {
        $pair = $item.Split('=')
        if ($pair.Count -eq 2 -and $pair[0] -in @('Overview', 'HealthDashboard') -and $pair[1] -eq 'true') { $otherSelected += $pair[0] }
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $scriptBytes = $utf8.GetBytes([IO.File]::ReadAllText($PSCommandPath).Replace("`r`n", "`n"))
        $helperHash = ([BitConverter]::ToString($sha.ComputeHash($scriptBytes))).Replace('-', '').ToLowerInvariant()
    } finally { $sha.Dispose() }
    return [pscustomobject][ordered]@{
        StartedUtc = [DateTime]::UtcNow.ToString('o'); UpdatedUtc = $null; EndedUtc = $null
        Status = 'Running'; ElapsedMs = 0; TaskType = $TaskType; ClientVersion = $ClientVersion
        FirstRequestUtc = $null; RequestWindowMs = $null; OtherSelectedModules = $otherSelected
        SelectedSections = $selected; SelectionProvided = ($SelectedSections -ne '')
        PlannedRequests = $planned; PauseSeconds = $PauseSeconds; DataLogs = $DataLogs
        HelperSha256 = $helperHash
        QueryContractSha256 = '3d304c868585586526c22255a3bbe38d05ad111e74b62e6d0e3827adb70d56d7'
        QueryEngine = 'Root API automatic selection; engine identity/version not observed'
        RequestWallTimeMs = 0; PausesScheduled = 0; ServerEvaluationMs = 0
        ParsedEvaluationCount = 0; UnparsedEvaluationCount = 0
        SlowestRequests = @(); FailureExamples = @(); Sections = [pscustomobject]@{}
    }
}
# After every request: adds its timing and outcome to the run totals and the
# per-section totals, keeps the 10 slowest requests and the first 20 failures,
# and copies a few aggregate counts (computers, relays, server version) into
# the summary. Only query numbers are kept, never capture names or answers.
function Update-RequestContext($outcome, $elapsed, $evaluation, $answer) {
    if ($null -eq $state.Run) { return }
    $run = $state.Run
    $run.RequestWallTimeMs += $elapsed
    if ($state.FinalCode -eq 0) { $run.PausesScheduled++ }
    $evaluationMs = Convert-EvaluationMs $evaluation
    if ($null -ne $evaluationMs) {
        $run.ServerEvaluationMs += $evaluationMs
        $run.ParsedEvaluationCount++
    } elseif (-not [string]::IsNullOrWhiteSpace($evaluation)) { $run.UnparsedEvaluationCount++ }
    $section = 'Other'
    foreach ($mapping in @(@('General_Info_', 'General'), @('Root_Server_Info_', 'Root'), @('Relay_Server_Info_', 'Relays'), @('Relay_Affiliation_Info_', 'RelayAffiliation'), @('Client_Settings_Info_', 'ClientSettings'), @('Client_Info_', 'Clients'), @('Operator_Info_', 'Operators'), @('Content_Info_', 'Content'), @('Property_Info_', 'Properties'), @('Action_Info_', 'Actions'))) {
        if ([IO.Path]::GetFileName($Capture).StartsWith($mapping[0])) { $section = $mapping[1]; break }
    }
    if ($null -eq $run.Sections.PSObject.Properties[$section]) {
        $run.Sections | Add-Member -NotePropertyName $section -NotePropertyValue ([pscustomobject]@{ Requests = 0; Failures = 0; WallTimeMs = 0 })
    }
    $stats = $run.Sections.$section
    $stats.Requests++; $stats.WallTimeMs += $elapsed
    if ($outcome -ne 'Success') { $stats.Failures++ }
    # Keep support references, not capture names (which contain hostnames) or answers.
    $sample = [pscustomobject]@{ QueryId = ('DI-{0:d3}' -f $QueryNumber); Section = $section; Resource = $Resource; Outcome = $outcome; WallTimeMs = $elapsed; ServerEvaluation = $evaluation }
    $run.SlowestRequests = @(@($run.SlowestRequests) + @($sample) | Sort-Object WallTimeMs -Descending | Select-Object -First 10)
    if ($outcome -ne 'Success' -and @($run.FailureExamples).Count -lt 20) { $run.FailureExamples = @($run.FailureExamples) + @($sample) }
    # Only successful, explicitly labelled aggregate answers may enter environment context.
    if ($outcome -eq 'Success' -and $contextFields.ContainsKey($QueryNumber)) {
        $spec = $contextFields[$QueryNumber]
        if ($answer -match ('^' + [regex]::Escape($spec[1]) + '\s*(.+)$')) {
            $value = $Matches[1].Trim()
            if ([string]::IsNullOrWhiteSpace($value)) { return }
            if ($spec[2] -eq 'count') {
                if ($value -notmatch '^\d+$') { return }
                $value = [long]$value
            } else { $value = Limit-ContextText $value }
            $state.Environment.Deployment.($spec[0]) = $value
            $state.Environment.Sources | Add-Member -NotePropertyName $spec[0] -NotePropertyValue ('DI-{0:d3}' -f $QueryNumber) -Force
        }
    }
}
# Writes the plain-text diagnostics summary next to the state file. A person
# can read it without opening the JSON or the CSV.
function Write-Summary($value) {
    $run = $value.Run
    if ($null -eq $run) { return }
    $lines = New-Object 'Collections.Generic.List[string]'
    $lines.Add('Deployment Information collection diagnostics')
    $lines.Add(('Status: {0}; BigFix exit code: {1}; request failures: {2}' -f $run.Status, $value.FinalCode, $value.Errors))
    $lines.Add(('Last outcome: {0}' -f $value.LastOutcome))
    if ($run.Status -eq 'Running') { $lines.Add('This is a progress snapshot. Completion has not been confirmed.') }
    $lines.Add(('UTC start: {0}; last update: {1}; end: {2}' -f $run.StartedUtc, $run.UpdatedUtc, (Format-Known $run.EndedUtc)))
    $lines.Add(('Task: {0}; client version: {1}' -f $run.TaskType, (Format-Known $run.ClientVersion)))
    $lines.Add(('Selected sections: {0}' -f $(if ($run.SelectionProvided) { ($run.SelectedSections -join ', ') } else { 'Not supplied' })))
    $lines.Add(('API requests attempted: {0}; planned: {1}; data logs: {2}' -f $value.Requests, $(if ($run.SelectionProvided) { $run.PlannedRequests } else { 'Unknown' }), $run.DataLogs))
    $lines.Add('')
    $lines.Add('Timing')
    $lines.Add(('Diagnostic window: {0}' -f (Format-Duration $run.ElapsedMs)))
    $lines.Add('The diagnostic window starts at initialization and excludes earlier backup/setup. In Day 1 it can include selected dashboard modules before Deployment Information.')
    $lines.Add(('Other selected Day 1 modules: {0}' -f $(if (@($run.OtherSelectedModules).Count) { $run.OtherSelectedModules -join ', ' } else { 'None' })))
    if ($null -ne $run.FirstRequestUtc) {
        $lines.Add(('Deployment Information window: {0}; first request UTC: {1}' -f (Format-Duration $run.RequestWindowMs), $run.FirstRequestUtc))
        $lines.Add('This window starts with its first API request, includes later pacing/local capture/log conversion, and excludes earlier initialization/login/dashboard modules.')
    } else { $lines.Add('Deployment Information window: Unavailable; no API request has started.') }
    $lines.Add(('Sum of API request wall times: {0}' -f (Format-Duration $run.RequestWallTimeMs)))
    $lines.Add('Request wall time includes CLI execution and response append. It excludes PowerShell startup, pacing and data-log conversion.')
    if ($run.PauseSeconds -ge 0) {
        $lines.Add(('Configured pause: {0} seconds; estimated scheduled pacing: {1} ({2} pauses).' -f $run.PauseSeconds, (Format-Duration ($run.PausesScheduled * $run.PauseSeconds * 1000)), $run.PausesScheduled))
        $lines.Add('Pacing is an estimate from requests returned without a fatal code, not a measured delay. An interrupted action may not execute its next pause.')
    } else { $lines.Add('Configured pacing was not supplied.') }
    $lines.Add(('Reported server evaluation time: {0}; parsed responses: {1}; unrecognized durations: {2}.' -f (Format-Duration $run.ServerEvaluationMs), $run.ParsedEvaluationCount, $run.UnparsedEvaluationCount))
    $lines.Add('Server evaluation time is only the duration returned by the query engine. It is not end-to-end request time; missing values are not treated as zero-duration queries.')
    $lines.Add('')
    $lines.Add('Environment')
    foreach ($field in $value.Environment.Deployment.PSObject.Properties) {
        $source = $value.Environment.Sources.($field.Name)
        $lines.Add(('{0}: {1}; source: {2}' -f $field.Name, (Format-Known $field.Value), (Format-Known $source)))
    }
    $lines.Add('Unavailable deployment values mean the required section was not selected, its answer was absent, or its request failed. They do not mean zero.')
    $lines.Add('ActiveComputerCount uses the existing last-report-time query with a 24-hour window.')
    $lines.Add('Local root hardware at initialization (OS-reported resources; a VM reports its assigned resources):')
    foreach ($field in $value.Environment.LocalRootHardware.PSObject.Properties) { $lines.Add(('  {0}: {1}' -f $field.Name, (Format-Known $field.Value))) }
    foreach ($warning in $value.Environment.DiscoveryWarnings) { $lines.Add(('Context note: {0}' -f $warning)) }
    $lines.Add(('Query engine: {0}' -f $run.QueryEngine))
    $lines.Add('')
    $lines.Add('Sections (requests / failures / summed request wall time)')
    foreach ($section in $run.Sections.PSObject.Properties) { $lines.Add(('{0}: {1} / {2} / {3}' -f $section.Name, $section.Value.Requests, $section.Value.Failures, (Format-Duration $section.Value.WallTimeMs))) }
    $lines.Add('')
    $lines.Add('Slowest requests (up to 10, by request wall time)')
    foreach ($request in $run.SlowestRequests) { $lines.Add(('{0} | {1} | {2} | {3} | server evaluation: {4}' -f $request.QueryId, $request.Section, $request.Outcome, (Format-Duration $request.WallTimeMs), (Format-Known $request.ServerEvaluation))) }
    $lines.Add('')
    $lines.Add('Failure examples (up to 20; CSV contains every attempted request)')
    foreach ($request in $run.FailureExamples) { $lines.Add(('{0} | {1} | {2}' -f $request.QueryId, $request.Section, $request.Outcome)) }
    $lines.Add('')
    $lines.Add(('Helper SHA-256: {0}' -f $run.HelperSha256))
    $lines.Add(('Shipped query contract SHA-256: {0}' -f $run.QueryContractSha256))
    $lines.Add('These files support runtime estimates and repeated measurements, not deployment rankings. Compare the same queries, versions, sections, pacing and log settings. Database/storage performance, cache state and concurrent load are not characterized here.')
    $summary = Join-Path ([IO.Path]::GetDirectoryName($StateFile)) ([IO.Path]::GetFileNameWithoutExtension($StateFile) + '_Summary.txt')
    [IO.File]::WriteAllLines($summary, $lines, $utf8)
}
# The query numbers whose answers are reused in the summary: query number,
# field name, the label the answer starts with, and whether it is a count.
$contextFields = @{
    14 = @('ComputerCount', 'Number of Computers:', 'count')
    15 = @('ActiveComputerCount', 'Number of Active Computers:', 'count')
    16 = @('RelayCount', 'Number of Relays:', 'count')
    20 = @('ServerVersionCounts', 'BES Server Version Counts:', 'text')
    30 = @('ServerVersionCounts', 'BES Server Version Counts:', 'text')
    33 = @('RootServersReportedCpu', 'BES Server CPU:', 'text')
    34 = @('RootServersReportedRam', 'BES Server RAM:', 'text')
    35 = @('RootServersReportedOs', 'BES Server OS:', 'text')
}

# Saves the run state as JSON after every request and rewrites the summary.
# State is kept in a file because each request is a separate process.
function Save-State($value) {
    if ($null -ne $value.Run) {
        $now = [DateTime]::UtcNow
        $value.Run.UpdatedUtc = $now.ToString('o')
        $started = [DateTime]::Parse($value.Run.StartedUtc, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind)
        $value.Run.ElapsedMs = [Math]::Max(0, [Math]::Round(($now - $started.ToUniversalTime()).TotalMilliseconds))
        if ($null -ne $value.Run.FirstRequestUtc) {
            $firstRequest = [DateTime]::Parse($value.Run.FirstRequestUtc, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind)
            $value.Run.RequestWindowMs = [Math]::Max(0, [Math]::Round(($now - $firstRequest.ToUniversalTime()).TotalMilliseconds))
        }
        if ($value.Run.Status -ne 'Running') { $value.Run.EndedUtc = $value.Run.UpdatedUtc }
    }
    [IO.File]::WriteAllText($StateFile, ($value | ConvertTo-Json -Depth 8), $utf8)
    Write-Summary $value
}
# Appends one row per request to the CSV log: query number, outcome, CLI exit
# code, HTTP status, elapsed time and the server's evaluation time.
function Write-Row($outcome, $cliCode, $httpCode, $elapsed, $evaluation) {
    [pscustomobject][ordered]@{
        Utc = [DateTime]::UtcNow.ToString('o')
        QueryId = ('DI-{0:d3}' -f $QueryNumber)
        Resource = $Resource
        Capture = [IO.Path]::GetFileName($Capture)
        Outcome = $outcome
        CliExitCode = $cliCode
        HttpStatus = $httpCode
        WallTimeMs = $elapsed
        ServerEvaluation = $evaluation
        ConsecutiveAvailabilityFailures = $state.ConsecutiveAvailabilityFailures
    } | Export-Csv -LiteralPath $CsvFile -NoTypeInformation -Append -Encoding UTF8
}
# MAIN. Everything below runs inside one try so any unexpected failure ends
# in the catch block at the bottom with exit code 24005.
try {
    # INIT: create the run record and the local context, write the first state
    # and summary, and exit. No request is sent to the server.
    if ($Mode -eq 'Init') {
        $run = New-RunContext
        $environment = Get-LocalContext
        $state = [pscustomobject]@{
            Requests = 0; Errors = 0; PermissionErrors = 0; QueryErrors = 0
            AvailabilityFailures = 0; ConsecutiveAvailabilityFailures = 0
            LastOutcome = 'Initialized'; FinalCode = 0
            SchemaVersion = 2; Run = $run; Environment = $environment
        }
        Save-State $state
        Write-Row 'Initialized' 0 '' 0 ''
        exit 0
    }
    # Every mode after Init starts by reloading the state saved by the last call.
    $state = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
    # LOGIN: the task ran iem login and passes its exit code in. Record it. A
    # failed login sets 24001 so the task stops before any query is sent.
    if ($Mode -eq 'Login') {
        $state.LastOutcome = if ($NativeExitCode -eq 0) { 'LoginSucceeded' } else { 'LoginFailed' }
        if ($NativeExitCode -ne 0) { $state.FinalCode = 24001; $state.Run.Status = 'Stopped' }
        Save-State $state
        Write-Row $state.LastOutcome $NativeExitCode '' 0 ''
        exit $state.FinalCode
    }
    # FINISH: if any request failed the run ends with 24004 so the action shows
    # as failed and the gap in the capture is visible. Otherwise it is Completed.
    if ($Mode -eq 'Finish') {
        if ($state.Errors -gt 0 -and $state.FinalCode -eq 0) { $state.FinalCode = 24004 }
        $state.LastOutcome = if ($state.FinalCode -eq 0) { 'Completed' } else { 'Incomplete' }
        $state.Run.Status = $state.LastOutcome
        Save-State $state
        Write-Row $state.LastOutcome 0 '' 0 ''
        exit $state.FinalCode
    }
    # REQUEST: run the IEM CLI once for this query (or resource) and time it.
    # The only program started is the one named by -IemPath.
    if ($null -eq $state.Run.FirstRequestUtc) { $state.Run.FirstRequestUtc = [DateTime]::UtcNow.ToString('o') }
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $IemPath
    $start.Arguments = 'GET ' + $Resource
    if ($Resource -eq 'query') { $start.Arguments += ' --relevance=' + $EncodedRelevance }
    $responseFile = $StateFile + '.response.xml'
    if ([IO.File]::Exists($responseFile)) { [IO.File]::Delete($responseFile) }
    $start.Arguments += ' --outFile "' + $responseFile + '"'
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardOutputEncoding = $utf8
    $start.StandardErrorEncoding = $utf8
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    [void]$process.Start()
    # Ask the CLI to write XML natively. Its redirected stdout can be UTF-16
    # even when the XML declares UTF-8; --outFile avoids that transport conversion.
    $outTask = $process.StandardOutput.ReadToEndAsync()
    $errTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $stdout = $outTask.Result
    $stderr = $errTask.Result
    # Append the CLI's native XML answer to the capture file byte for byte and
    # add a newline. Earlier answers in the same file are kept as they are.
    $captureStream = [IO.File]::Open($Capture, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::Read)
    $responseOffset = $captureStream.Length
    $captureStream.Position = $responseOffset
    if ([IO.File]::Exists($responseFile)) {
        $nativeResponse = [IO.File]::OpenRead($responseFile)
        try { $nativeResponse.CopyTo($captureStream) } finally { $nativeResponse.Dispose() }
    }
    $captureStream.WriteByte(10)
    $captureStream.Dispose()
    $cliCode = $process.ExitCode
    $watch.Stop()
    $state.Requests++
    $httpCode = ''
    # Read status codes only from explicit HTTP/status diagnostics, never from metric answers.
    $prefixStream = [IO.File]::OpenRead($Capture)
    $prefixStream.Position = $responseOffset
    $prefixReader = New-Object IO.StreamReader($prefixStream, $utf8, $true)
    $prefixBuffer = New-Object char[] 4096
    $prefixLength = $prefixReader.Read($prefixBuffer, 0, $prefixBuffer.Length)
    $stdoutPrefix = if ($prefixLength -gt 0) { -join $prefixBuffer[0..($prefixLength - 1)] } else { '' }
    $prefixReader.Dispose()
    $statusText = $stderr + "`n" + $stdout
    if ($stdoutPrefix -notmatch '^\s*(?:<\?xml|<BESAPI)') { $statusText += "`n" + $stdoutPrefix }
    $httpMatch = [regex]::Match($statusText, '(?im)^.*(?:HTTP|status)[^\r\n]*?\b([45]\d\d)\b')
    if ($httpMatch.Success) { $httpCode = $httpMatch.Groups[1].Value }
    # Check that the answer is a complete BESAPI document and pick out its
    # evaluation time and any error element. DTDs are prohibited and no external
    # resolver is used, so the answer cannot pull in anything from elsewhere.
    $evaluation = ''
    $contextAnswer = $null
    $validResponse = $false
    $queryError = $false
    $isBesApi = $false
    $hasQuery = $false
    $hasResult = $false
    $hasError = $false
    try {
        $settings = New-Object Xml.XmlReaderSettings
        $settings.DtdProcessing = [Xml.DtdProcessing]::Prohibit
        $settings.XmlResolver = $null
        $responseStream = [IO.File]::OpenRead($Capture)
        $responseStream.Position = $responseOffset
        $reader = [Xml.XmlReader]::Create($responseStream, $settings)
        while ($reader.Read()) {
            if ($reader.NodeType -ne [Xml.XmlNodeType]::Element) { continue }
            if ($reader.Depth -eq 0 -and $reader.LocalName -eq 'BESAPI') { $isBesApi = $true }
            if ($reader.Depth -eq 1 -and $reader.LocalName -eq 'Query') { $hasQuery = $true }
            if ($reader.Depth -eq 2 -and $reader.LocalName -eq 'Result' -and $hasQuery) { $hasResult = $true }
            if ($reader.LocalName -eq 'Error') { $hasError = $true }
            if ($reader.Depth -eq 3 -and $reader.LocalName -eq 'Answer' -and $contextFields.ContainsKey($QueryNumber) -and $null -eq $contextAnswer) { $contextAnswer = $reader.ReadElementContentAsString() }
            if ($reader.LocalName -eq 'Time') { $evaluation = $reader.ReadElementContentAsString() }
        }
        $validResponse = $isBesApi -and ($Resource -ne 'query' -or $hasResult)
        $queryError = $isBesApi -and $hasError
    } catch {
        $validResponse = $false
        $queryError = $false
    } finally {
        if ($null -ne $reader) { $reader.Dispose() }
        if ($null -ne $responseStream) { $responseStream.Dispose() }
    }
    # OUTCOME RULES. 401 authentication failure. 403 permission failure. 408, 429
    # and 5xx availability failure. Any other HTTP error request failure. An
    # error inside a valid answer is a query failure. A non-zero CLI exit code or
    # an incomplete answer is an availability failure. Anything else is success.
    if ($httpCode -eq '401') { $outcome = 'AuthenticationFailure' }
    elseif ($httpCode -eq '403') { $outcome = 'PermissionFailure' }
    elseif ($httpCode -eq '408' -or $httpCode -eq '429' -or $httpCode -match '^5\d\d$') { $outcome = 'AvailabilityFailure' }
    elseif ($httpCode) { $outcome = 'RequestFailure' }
    elseif ($queryError) { $outcome = 'QueryFailure' }
    elseif ($cliCode -ne 0 -or -not $validResponse) { $outcome = 'AvailabilityFailure' }
    else { $outcome = 'Success' }
    # STOP RULES. Permission and query failures are counted and the run goes on,
    # because one bad query should not lose the rest. A 401 stops the run (24002).
    # Three availability failures in a row stop it (24003). Any success resets
    # the consecutive count.
    $state.LastOutcome = $outcome
    if ($outcome -eq 'AvailabilityFailure') {
        $state.AvailabilityFailures++
        $state.ConsecutiveAvailabilityFailures++
    } else { $state.ConsecutiveAvailabilityFailures = 0 }
    if ($outcome -ne 'Success') {
        $state.Errors++
        if ($outcome -eq 'PermissionFailure') { $state.PermissionErrors++ }
        if ($outcome -eq 'QueryFailure') { $state.QueryErrors++ }
        if ($outcome -eq 'AuthenticationFailure') { $state.FinalCode = 24002 }
        if ($state.ConsecutiveAvailabilityFailures -ge 3) { $state.FinalCode = 24003 }
    }
    if ($outcome -ne 'Success') {
        # Put a visible ERROR line in the capture so the gap is obvious to the
        # Report Builder and to a person reading the file.
        $marker = 'ERROR: Query line {0} failed: {1}; CLI exit {2}; HTTP {3}. See deployment collector diagnostics.' -f $QueryNumber, $outcome, $cliCode, $httpCode
        [IO.File]::AppendAllText($Capture, $marker + "`r`n", $utf8)
    }
    Update-RequestContext $outcome $watch.ElapsedMilliseconds $evaluation $contextAnswer
    if ($state.FinalCode -ne 0) { $state.Run.Status = 'Stopped' }
    Save-State $state
    Write-Row $outcome $cliCode $httpCode $watch.ElapsedMilliseconds $evaluation
    $process.Dispose()
    if ([IO.File]::Exists($responseFile)) { [IO.File]::Delete($responseFile) }
    exit $state.FinalCode
} catch {
    # Any unexpected failure of this helper ends here: record it as 24005, clean
    # up, and exit. The details of the exception are deliberately not recorded.
    # Do not print raw CLI output, arguments, or exception details into diagnostics.
    try {
        if ($responseFile -and [IO.File]::Exists($responseFile)) { [IO.File]::Delete($responseFile) }
        if ($null -ne $captureStream) { $captureStream.Dispose() }
        if ($null -ne $reader) { $reader.Dispose() }
        if ($null -ne $responseStream) { $responseStream.Dispose() }
        if ($null -ne $state) {
            $state.LastOutcome = 'LocalCollectorFailure'
            $state.FinalCode = 24005
            if ($null -ne $state.Run) { $state.Run.Status = 'Stopped' }
            Save-State $state
            Write-Row 'LocalCollectorFailure' 0 '' 0 ''
        }
    } catch { }
    exit 24005
}
