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
    [int]$NativeExitCode = 0
)
$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
function Save-State($value) {
    [IO.File]::WriteAllText($StateFile, ($value | ConvertTo-Json -Depth 5), $utf8)
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
        $state = [pscustomobject]@{
            Requests = 0; Errors = 0; PermissionErrors = 0; QueryErrors = 0
            AvailabilityFailures = 0; ConsecutiveAvailabilityFailures = 0
            LastOutcome = 'Initialized'; FinalCode = 0
        }
        Save-State $state
        Write-Row 'Initialized' 0 '' 0 ''
        exit 0
    }
    $state = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
    if ($Mode -eq 'Login') {
        $state.LastOutcome = if ($NativeExitCode -eq 0) { 'LoginSucceeded' } else { 'LoginFailed' }
        if ($NativeExitCode -ne 0) { $state.FinalCode = 24001 }
        Save-State $state
        Write-Row $state.LastOutcome $NativeExitCode '' 0 ''
        exit $state.FinalCode
    }
    if ($Mode -eq 'Finish') {
        if ($state.Errors -gt 0 -and $state.FinalCode -eq 0) { $state.FinalCode = 24004 }
        $state.LastOutcome = if ($state.FinalCode -eq 0) { 'Completed' } else { 'Incomplete' }
        Save-State $state
        Write-Row $state.LastOutcome 0 '' 0 ''
        exit $state.FinalCode
    }
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
            Save-State $state
            Write-Row 'LocalCollectorFailure' 0 '' 0 ''
        }
    } catch { }
    exit 24005
}
