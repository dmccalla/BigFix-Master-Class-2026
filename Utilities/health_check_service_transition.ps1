# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][ValidateSet('Stopped', 'Running')][string]$Target,
    [string]$LogPath
)

# BEGIN INLINE SERVICE CONTROL
# This body is embedded in the BES tasks by service_transition_commands.py.
# Pending is a Windows service state, not evidence that an elapsed limit failed.
$ErrorActionPreference = 'Stop';
if (-not $LogPath) {
    $LogPath = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'MasterClassWorkbench\ServiceTransitions.log';
};
function Write-HCServiceStatus([string]$Message) {
    $entry = [DateTime]::UtcNow.ToString('o') + ' [' + $Name + '] ' + $Message;
    Write-Output $entry;
    try {
        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($LogPath));
        [IO.File]::AppendAllText($LogPath, $entry + [Environment]::NewLine);
    } catch {
        Write-Warning ('Cannot write service status log: ' + $_.Exception.Message);
    };
};
function Wait-HCServiceState($Controller, [string]$DesiredState) {
    $pending = if ($DesiredState -eq 'Stopped') { 'StopPending' } else { 'StartPending' };
    $clock = [Diagnostics.Stopwatch]::StartNew();
    $nextLog = 0;
    while ($true) {
        $Controller.Refresh();
        $state = $Controller.Status.ToString();
        if ($state -eq $DesiredState) {
            Write-HCServiceStatus ($state + ' after ' + [Math]::Floor($clock.Elapsed.TotalSeconds) + ' seconds');
            return;
        };
        if ($state -ne $pending) {
            throw ('Expected ' + $DesiredState + ' or ' + $pending + ', found ' + $state);
        };
        if ($clock.Elapsed.TotalSeconds -ge $nextLog) {
            Write-HCServiceStatus ('Waiting for ' + $DesiredState + '; state=' + $state + '; elapsed=' + [Math]::Floor($clock.Elapsed.TotalSeconds) + ' seconds');
            $nextLog = $clock.Elapsed.TotalSeconds + 30;
        };
        Start-Sleep -Seconds 1;
    };
};
$s = $null;
try {
    $s = (@(Get-Service -Name $Name -ErrorAction SilentlyContinue) + @(Get-Service -DisplayName $Name -ErrorAction SilentlyContinue))[0];
    if ($null -eq $s) { throw 'Service not found' };
    $s.Refresh();
    Write-HCServiceStatus ('Requested ' + $Target + '; initial state=' + $s.Status);
    if ($Target -eq 'Stopped') {
        if ($s.Status -eq 'StartPending') { Wait-HCServiceState $s 'Running' };
        if ($s.Status -ne 'Stopped' -and $s.Status -ne 'StopPending') {
            Stop-Service -InputObject $s -Force -NoWait -ErrorAction Stop;
        };
    } else {
        if ($s.Status -eq 'StopPending') { Wait-HCServiceState $s 'Stopped' };
        if ($s.Status -ne 'Running' -and $s.Status -ne 'StartPending') { $s.Start() };
    };
    Wait-HCServiceState $s $Target;
} catch {
    $failure = $_.Exception.Message;
    Write-HCServiceStatus ('ERROR: ' + $failure);
    if ($null -ne $s) {
        try {
            $s.Refresh();
            if ($s.Status -eq 'StopPending') {
                Write-HCServiceStatus 'Recovery: waiting for the outstanding stop before restoring Running';
                Wait-HCServiceState $s 'Stopped';
            };
            if ($s.Status -eq 'Stopped') {
                Write-HCServiceStatus 'Recovery: restoring Running after the failed operation';
                $s.Start();
                Wait-HCServiceState $s 'Running';
            } elseif ($s.Status -eq 'StartPending') {
                Wait-HCServiceState $s 'Running';
            };
            if ($s.Status -ne 'Running') { throw ('Service is ' + $s.Status + ', not Running') };
            Write-HCServiceStatus ('FAILED operation; final state=' + $s.Status);
        } catch {
            Write-HCServiceStatus ('RECOVERY FAILED: ' + $_.Exception.Message + '; last state=' + $s.Status + '; operator intervention required');
        };
    };
    throw ('Service operation failed for ' + $Name + ': ' + $failure);
};
