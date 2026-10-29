# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
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
$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
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
function Limit-ContextText($value) {
    if ($null -eq $value) { return $null }
    $clean = ([string]$value -replace '[\x00-\x1f\x7f]', ' ').Trim()
    if ($clean.Length -gt 512) { $clean = $clean.Substring(0, 512) + ' [truncated]' }
    return $clean
}
function Format-Known($value) {
    if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) { return 'Unavailable' }
    return [string]$value
}
function Format-Duration($milliseconds) {
    return [TimeSpan]::FromMilliseconds([Math]::Max(0, [double]$milliseconds)).ToString('c')
}
function Convert-EvaluationMs($value) {
    $match = [regex]::Match([string]$value, '^\s*(\d+(?:\.\d+)?)\s*(ms|s|us|milliseconds?|seconds?)\s*$', 'IgnoreCase,CultureInvariant')
    if (-not $match.Success) { return $null }
    $number = [double]::Parse($match.Groups[1].Value, [Globalization.CultureInfo]::InvariantCulture)
    $unit = $match.Groups[2].Value.ToLowerInvariant()
    if ($unit -eq 'us') { return $number / 1000 }
    if ($unit -eq 's' -or $unit.StartsWith('second')) { return $number * 1000 }
    return $number
}
function New-RunContext {
    # Counts are verified against the unchanged task requests by offline contracts.
    $counts = [ordered]@{ General = 26; Root = 8; Relays = 25; RelayAffiliation = 3; Clients = 21; ClientSettings = 17; Operators = 19; Content = 28; Properties = 12; Actions = 19 }
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
        QueryContractSha256 = '04177cfc60da51a5ac968d6dee8e3cf837157ae2be43169412d8af16643e3b73'
        QueryEngine = 'Root API automatic selection; engine identity/version not observed'
        RequestWallTimeMs = 0; PausesScheduled = 0; ServerEvaluationMs = 0
        ParsedEvaluationCount = 0; UnparsedEvaluationCount = 0
        SlowestRequests = @(); FailureExamples = @(); Sections = [pscustomobject]@{}
    }
}
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
try {
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
    $state = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
    if ($Mode -eq 'Login') {
        $state.LastOutcome = if ($NativeExitCode -eq 0) { 'LoginSucceeded' } else { 'LoginFailed' }
        if ($NativeExitCode -ne 0) { $state.FinalCode = 24001; $state.Run.Status = 'Stopped' }
        Save-State $state
        Write-Row $state.LastOutcome $NativeExitCode '' 0 ''
        exit $state.FinalCode
    }
    if ($Mode -eq 'Finish') {
        if ($state.Errors -gt 0 -and $state.FinalCode -eq 0) { $state.FinalCode = 24004 }
        $state.LastOutcome = if ($state.FinalCode -eq 0) { 'Completed' } else { 'Incomplete' }
        $state.Run.Status = $state.LastOutcome
        Save-State $state
        Write-Row $state.LastOutcome 0 '' 0 ''
        exit $state.FinalCode
    }
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
    if ($httpCode -eq '401') { $outcome = 'AuthenticationFailure' }
    elseif ($httpCode -eq '403') { $outcome = 'PermissionFailure' }
    elseif ($httpCode -eq '408' -or $httpCode -eq '429' -or $httpCode -match '^5\d\d$') { $outcome = 'AvailabilityFailure' }
    elseif ($httpCode) { $outcome = 'RequestFailure' }
    elseif ($queryError) { $outcome = 'QueryFailure' }
    elseif ($cliCode -ne 0 -or -not $validResponse) { $outcome = 'AvailabilityFailure' }
    else { $outcome = 'Success' }
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
