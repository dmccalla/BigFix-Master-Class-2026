# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Execute the shipped PowerShell with a fake service and clock, never real services."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from defusedxml import ElementTree as ET

from Utilities.service_transition_commands import powershell_body

POWERSHELL = shutil.which("powershell.exe") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(not POWERSHELL, reason="PowerShell is required")

HARNESS = r"""
$script:virtualSeconds = 0;
$script:starts = 0;
$script:stops = 0;
$script:stopAt = [int]$scenario.stopAfter;
$script:startAt = 0;
$script:fake = [pscustomobject]@{Status=[string]$scenario.initial; ServiceName='FakeService'};
$script:fake | Add-Member ScriptMethod Refresh {
    if ($this.Status -eq 'StopPending' -and $script:virtualSeconds -ge $script:stopAt) {
        $this.Status = 'Stopped';
    };
    if ($this.Status -eq 'StartPending' -and $script:virtualSeconds -ge $script:startAt) {
        $this.Status = 'Running';
    };
};
$script:fake | Add-Member ScriptMethod Start {
    $script:starts++;
    if ($scenario.failStart) { throw 'Synthetic start rejected' };
    if ($this.Status -eq 'StopPending') { throw 'Started before shutdown completed' };
    $this.Status = 'StartPending';
    $script:startAt = $script:virtualSeconds + [int]$scenario.startAfter;
};
function Get-Service {
    param($Name, $DisplayName, $ErrorAction);
    if (-not $scenario.missing -and (($Name -and -not $scenario.displayOnly) -or ($DisplayName -and $scenario.displayOnly))) { $script:fake };
};
function Stop-Service {
    param($InputObject, [switch]$Force, [switch]$NoWait, $ErrorAction);
    if (-not $NoWait) { throw 'Blocking stop is forbidden by the harness' };
    $script:stops++;
    if ($scenario.failBeforeStop) { throw 'Synthetic stop rejected' };
    $InputObject.Status = if ($scenario.unexpectedRunning) { 'Running' } else { 'StopPending' };
    if ($scenario.failAfterStop) { throw 'Synthetic error after stop accepted' };
};
function Start-Sleep {
    param([int]$Seconds);
    $script:virtualSeconds += $Seconds;
    if ($script:virtualSeconds -gt 7200) { throw 'Harness detected an endless wait' };
};
function New-TestClock {
    $watch = [pscustomobject]@{Started=$script:virtualSeconds};
    $watch | Add-Member ScriptProperty Elapsed {
        [TimeSpan]::FromSeconds($script:virtualSeconds - $this.Started);
    };
    return $watch;
};
$ok = $false;
$failure = '';
try {
    & { __BODY__ };
    $ok = $true;
} catch {
    $failure = $_.Exception.Message;
};
$result = [pscustomobject]@{
    ok=$ok; error=$failure; state=$script:fake.Status;
    starts=$script:starts; stops=$script:stops; seconds=$script:virtualSeconds;
};
Write-Output ('__HC_RESULT__' + ($result | ConvertTo-Json -Compress));
"""


def run_transition(
    tmp_path: Path, target: str, *, shipped_body: str | None = None, **scenario
):
    values = {"initial": "Running", "stopAfter": 0, "startAfter": 0, **scenario}
    log = tmp_path / "ServiceTransitions.log"
    ps_log = str(log).replace("'", "''")
    scenario_json = json.dumps(values).replace("'", "''")
    body = shipped_body or powershell_body("FakeService", target)
    # Substitute only the monotonic clock. All transition and recovery code is
    # the exact production body; fake Start-Sleep advances virtual time.
    body = body.replace("[Diagnostics.Stopwatch]::StartNew()", "(New-TestClock)")
    source = (
        f"$scenario = '{scenario_json}' | ConvertFrom-Json;\n"
        f"$LogPath = '{ps_log}';\n" + HARNESS.replace("__BODY__", body)
    )
    script = tmp_path / "harness.ps1"
    script.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    summary = next(
        line.removeprefix("__HC_RESULT__")
        for line in result.stdout.splitlines()
        if line.startswith("__HC_RESULT__")
    )
    return json.loads(summary), log.read_text(encoding="utf-8")


def test_twenty_two_minute_stop_completes_with_regular_progress(tmp_path):
    result, log = run_transition(tmp_path, "Stopped", stopAfter=22 * 60)
    assert result == {
        "ok": True,
        "error": "",
        "state": "Stopped",
        "starts": 0,
        "stops": 1,
        "seconds": 1320,
    }
    assert log.count("Waiting for Stopped") == 44
    assert "Stopped after 1320 seconds" in log


def test_start_longer_than_five_minutes_completes(tmp_path):
    result, log = run_transition(
        tmp_path, "Running", initial="Stopped", startAfter=6 * 60
    )
    assert result["ok"] and result["state"] == "Running"
    assert result["starts"] == 1 and result["seconds"] == 360
    assert "Running after 360 seconds" in log


def test_error_after_stop_waits_for_late_stop_and_restores_running(tmp_path):
    result, log = run_transition(
        tmp_path,
        "Stopped",
        stopAfter=22 * 60,
        failAfterStop=True,
    )
    assert not result["ok"]
    assert result["state"] == "Running" and result["starts"] == 1
    assert result["seconds"] == 1320
    assert "Synthetic error after stop accepted" in result["error"]
    assert "Recovery: waiting for the outstanding stop" in log
    assert "FAILED operation; final state=Running" in log


def test_rejected_stop_fails_without_restarting_running_service(tmp_path):
    result, log = run_transition(tmp_path, "Stopped", failBeforeStop=True)
    assert not result["ok"] and result["state"] == "Running"
    assert result["starts"] == 0
    assert "Synthetic stop rejected" in log


def test_unexpected_state_is_a_failure_not_a_success(tmp_path):
    result, log = run_transition(tmp_path, "Stopped", unexpectedRunning=True)
    assert not result["ok"] and result["state"] == "Running"
    assert "Expected Stopped or StopPending, found Running" in log


def test_recovery_failure_reports_operator_intervention(tmp_path):
    result, log = run_transition(tmp_path, "Running", initial="Stopped", failStart=True)
    assert not result["ok"] and result["state"] == "Stopped"
    assert result["starts"] == 2
    assert "RECOVERY FAILED" in log and "operator intervention required" in log


def test_start_waits_for_an_existing_stop_before_starting(tmp_path):
    result, _ = run_transition(
        tmp_path,
        "Running",
        initial="StopPending",
        stopAfter=22 * 60,
    )
    assert result["ok"] and result["state"] == "Running"
    assert result["seconds"] == 1320 and result["starts"] == 1


@pytest.mark.parametrize("target", ["Stopped", "Running"])
def test_already_at_target_does_not_request_another_transition(tmp_path, target):
    result, _ = run_transition(tmp_path, target, initial=target)
    assert result["ok"] and result["state"] == target
    assert result["starts"] == 0 and result["stops"] == 0


def test_missing_service_fails_clearly(tmp_path):
    result, log = run_transition(tmp_path, "Stopped", missing=True)
    assert not result["ok"] and "Service not found" in result["error"]
    assert "Service not found" in log


def test_service_can_be_resolved_by_display_name(tmp_path):
    result, _ = run_transition(tmp_path, "Stopped", displayOnly=True)
    assert result["ok"] and result["stops"] == 1


@pytest.mark.parametrize("passes", [1, 2])
@pytest.mark.parametrize("stop_error", [False, True])
def test_actual_direct_and_generated_task_commands_handle_a_late_stop(
    tmp_path,
    passes,
    stop_error,
):
    site = next(
        parent / "Tasks and Analyses"
        for parent in Path(__file__).resolve().parents
        if (parent / "Tasks and Analyses").is_dir()
    )
    body = None
    for task in sorted(site.rglob("*.bes")):
        lines = "\n".join(
            node.text or "" for node in ET.parse(task).iter("ActionScript")
        ).splitlines()
        for index, line in enumerate(lines):
            if not re.search(r"\$Name='[^']+'; \$Target='Stopped';", line):
                continue
            gate = next(value for value in lines[index + 1 :] if value.strip())
            if (2 if "{{exit code" in gate else 1) != passes:
                continue
            body = line.split('-Command "', 1)[1].removesuffix('"')
            for _ in range(passes):
                body = body.replace("{{", "{")
            break
        if body is not None:
            break
    assert body is not None, "No matching shipped service command"
    result, log = run_transition(
        tmp_path,
        "Stopped",
        shipped_body=body,
        stopAfter=22 * 60,
        failAfterStop=stop_error,
    )
    assert result["seconds"] == 1320
    assert result["ok"] is not stop_error
    assert result["state"] == ("Running" if stop_error else "Stopped")
    assert "elapsed=1290 seconds" in log


@pytest.mark.parametrize("stop_error", [False, True])
def test_native_powershell_exit_code_preserves_failure_after_recovery(
    tmp_path, stop_error
):
    scenario = {
        "initial": "Running",
        "stopAfter": 1320,
        "startAfter": 0,
        "failAfterStop": stop_error,
    }
    log_path = str(tmp_path / "service.log").replace("'", "''")
    body = powershell_body("FakeService", "Stopped").replace(
        "[Diagnostics.Stopwatch]::StartNew()",
        "(New-TestClock)",
    )
    source = (
        f"$scenario = '{json.dumps(scenario)}' | ConvertFrom-Json;\n"
        f"$LogPath = '{log_path}';\n" + HARNESS.split("$ok = $false;", 1)[0] + body
    )
    script = tmp_path / "exit_code.ps1"
    script.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == (1 if stop_error else 0), result.stdout + result.stderr
    if stop_error:
        assert "FAILED operation; final state=Running" in result.stdout
        assert "Service operation failed" in result.stderr
