# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
"""Execute the real diagnostic helper with a local fake IEM binary, without a server."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "Tasks and Analyses").is_dir()
)
HELPER = ROOT / "Tasks and Analyses/Support/DeploymentApiRequest.ps1"
pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or not shutil.which("powershell.exe"),
    reason="Executes the Windows PowerShell collector helper",
)
FAKE_IEM = r"""
using System;
class FakeIem {
    static int Main(string[] args) {
        Console.OutputEncoding = new System.Text.UTF8Encoding(false);
        string kind = "";
        for (int i = 0; i < args.Length; i++) {
            if (args[i].StartsWith("--relevance=")) kind = args[i].Replace("--relevance=", "");
            if (args[i] == "--outFile") {
                Console.SetOut(new System.IO.StreamWriter(args[++i], false, new System.Text.UTF8Encoding(false)) { AutoFlush = true });
            }
        }
        if (kind == "unauthorized") { Console.Error.WriteLine("HTTP Error 401: Unauthorized"); return 7; }
        if (kind == "unauthorized-stdout") { Console.WriteLine("HTTP status 401 Unauthorized"); return 7; }
        if (kind == "forbidden") { Console.Error.WriteLine("HTTP Error 403: Forbidden"); return 7; }
        if (kind == "server-error") { Console.Error.WriteLine("HTTP Error 503: Unavailable"); return 9; }
        if (kind == "rate-limit") { Console.Error.WriteLine("HTTP status 429 Too Many Requests"); return 9; }
        if (kind == "timeout") { Console.Error.WriteLine("Connection timed out"); return 8; }
        if (kind == "malformed") { Console.WriteLine("Not an XML response"); return 0; }
        if (kind == "query-error") {
            Console.WriteLine("<?xml version=\"1.0\"?><BESAPI><Query><Error>Unsupported inspector</Error></Query></BESAPI>"); return 0;
        }
        if (kind == "query-error-partial") {
            Console.WriteLine("<?xml version=\"1.0\"?><BESAPI><Query><Result><Answer type=\"integer\">14</Answer></Result><Error>This operation is not supported.</Error></Query></BESAPI>"); return 0;
        }
        if (kind == "unicode") {
            Console.WriteLine("<?xml version=\"1.0\" encoding=\"UTF-8\"?><BESAPI><Query><Result><Answer type=\"string\">Caf\u00e9 \u5ba2\u6237 &amp; value</Answer></Result></Query></BESAPI>"); return 0;
        }
        if (kind == "large") {
            Console.WriteLine("<?xml version=\"1.0\" encoding=\"UTF-8\"?><BESAPI><Query><Result><Answer type=\"string\">" + new string('x', 2000000) + "</Answer></Result></Query></BESAPI>"); return 0;
        }

        if (kind == "slow") System.Threading.Thread.Sleep(800);
        string labelled = null;
        if (kind == "nodes" || kind == "partial-nodes") labelled = "Number of Computers: 42";
        if (kind == "zero-relays") labelled = "Number of Relays: 0";
        if (kind == "license-secret") labelled = "License Site Number: PRIVATE_LICENSE";
        if (kind == "active-nodes") labelled = "Number of Active Computers: 32";
        if (kind == "server-versions") labelled = "BES Server Version Counts: 11.0.6--2";
        if (kind == "blank-versions") labelled = "BES Server Version Counts: ";
        if (kind == "server-cpu") labelled = "BES Server CPU: Lab CPU";
        if (kind == "server-ram") labelled = "BES Server RAM: 64 GB";
        if (kind == "server-os") labelled = "BES Server OS: Lab OS";
        if (kind == "hardware-secret") labelled = "BES Server Hardware Information: PRIVATE_HARDWARE";
        if (labelled != null) {
            string error = kind == "partial-nodes" ? "<Error>Unsupported operation</Error>" : "";
            Console.WriteLine("<?xml version=\"1.0\"?><BESAPI><Query><Result><Answer type=\"string\">" + labelled + "</Answer></Result>" + error + "</Query></BESAPI>"); return 0;
        }
        if (kind == "seconds" || kind == "no-unit") {
            Console.WriteLine("<?xml version=\"1.0\"?><BESAPI><Query><Result/><Evaluation><Time>" + (kind == "seconds" ? "0.5s" : "0.5") + "</Time></Evaluation></Query></BESAPI>"); return 0;
        }
        string answer = kind == "empty" ? "" : "<Answer type=\"string\">PRIVATE_METRIC &amp; 401</Answer>";
        Console.WriteLine("<?xml version=\"1.0\" encoding=\"UTF-8\"?><BESAPI><Query><Result>" + answer + "</Result><Evaluation><Time>0.25ms</Time></Evaluation></Query></BESAPI>");
        return 0;
    }
}
"""


@pytest.fixture(scope="module")
def fake_iem(tmp_path_factory):
    directory = tmp_path_factory.mktemp("fake-iem")
    source = directory / "FakeIem.cs"
    binary = directory / "FakeIem.exe"
    source.write_text(FAKE_IEM, encoding="utf-8")
    compile_script = directory / "compile.ps1"
    compile_script.write_text(
        "param($Source, $Output)\n$ErrorActionPreference='Stop'\nAdd-Type -TypeDefinition (Get-Content -LiteralPath $Source -Raw) -Language CSharp -OutputType ConsoleApplication -OutputAssembly $Output\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(compile_script),
            str(source),
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return binary


@pytest.fixture
def collector(tmp_path, fake_iem):
    state = tmp_path / "state.json"
    log = tmp_path / "diagnostics.csv"
    capture = tmp_path / "capture.xml"
    number = 0

    def call(mode, response=None, native=0):
        nonlocal number
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(HELPER),
            "-Mode",
            mode,
            "-StateFile",
            str(state),
            "-CsvFile",
            str(log),
            "-Capture",
            str(capture),
            "-NativeExitCode",
            str(native),
        ]
        if response is not None:
            number += 1
            command += [
                "-IemPath",
                str(fake_iem),
                "-Resource",
                "query",
                "-EncodedRelevance",
                response,
                "-QueryNumber",
                str(number),
            ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert not result.stdout and not result.stderr, (result.stdout, result.stderr)
        return result.returncode

    assert call("Init") == 0
    return call, state, log, capture


def test_success_empty_result_and_metric_401_are_not_failures(collector):
    call, state, log, capture = collector
    assert call("Request", "success") == 0
    assert call("Request", "empty") == 0
    assert call("Finish") == 0
    assert json.loads(state.read_text())["Errors"] == 0
    rows = list(csv.DictReader(log.open(encoding="utf-8-sig")))
    assert rows[1]["ServerEvaluation"] == "0.25ms"
    assert rows[1]["HttpStatus"] == ""
    assert "PRIVATE_METRIC" not in log.read_text(encoding="utf-8-sig")
    assert "PRIVATE_METRIC &amp; 401" in capture.read_text()


@pytest.mark.parametrize("response", ["unauthorized", "unauthorized-stdout"])
def test_authentication_failure_stops_immediately(collector, response):
    call, state, _, capture = collector
    assert call("Request", response) == 24002
    assert json.loads(state.read_text())["Requests"] == 1
    assert "AuthenticationFailure" in capture.read_text()
    assert json.loads(state.read_text())["Run"]["Status"] == "Stopped"
    assert "24002" in state.with_name("state_Summary.txt").read_text()
    assert not Path(str(state) + ".response.xml").exists()


def test_login_failure_has_its_own_code(collector):
    call, _, log, _ = collector
    assert call("Login", native=7) == 24001
    assert "LoginFailed" in log.read_text(encoding="utf-8-sig")


@pytest.mark.parametrize(
    "response", ["server-error", "timeout", "rate-limit", "malformed"]
)
def test_three_consecutive_availability_failures_stop(collector, response):
    call, state, _, _ = collector
    assert call("Request", response) == 0
    assert call("Request", response) == 0
    assert call("Request", response) == 24003
    data = json.loads(state.read_text())
    assert data["Requests"] == 3  # No automatic retries.
    assert data["ConsecutiveAvailabilityFailures"] == 3
    assert data["Run"]["Status"] == "Stopped"
    assert "24003" in state.with_name("state_Summary.txt").read_text()


@pytest.mark.parametrize("query_response", ["query-error", "query-error-partial"])
def test_permission_and_query_errors_continue_then_report_incomplete(
    collector, query_response
):
    call, state, _, capture = collector
    assert call("Request", "forbidden") == 0
    assert call("Request", query_response) == 0
    assert call("Request", "success") == 0
    assert call("Finish") == 24004
    data = json.loads(state.read_text())
    assert data["PermissionErrors"] == data["QueryErrors"] == 1
    assert data["AvailabilityFailures"] == 0
    assert "ERROR: Query line 2 failed: QueryFailure" in capture.read_text()


def test_empty_success_resets_the_consecutive_failure_gate(collector):
    call, state, _, _ = collector
    assert call("Request", "timeout") == 0
    assert call("Request", "timeout") == 0
    assert call("Request", "empty") == 0
    assert call("Request", "timeout") == 0
    assert json.loads(state.read_text())["ConsecutiveAvailabilityFailures"] == 1


def test_missing_diagnostic_state_has_its_own_code(collector):
    call, state, _, _ = collector
    # A missing state file is a local diagnostic failure, independent of API availability.
    state.unlink()
    assert call("Finish") == 24005


def test_embedded_helper_matches_reviewable_source():
    from defusedxml import ElementTree as ET

    task = next(
        (ROOT / "Tasks and Analyses/Individual Tasks").glob(
            "* -- Collect Deployment Information (2.0).bes"
        )
    )
    script = ET.parse(task).findtext(".//ActionScript")
    embedded = script.split("createfile until DI_REQUEST_HELPER_EOF\n", 1)[1].split(
        "DI_REQUEST_HELPER_EOF\n", 1
    )[0]
    assert embedded.replace("{{", "{") == HELPER.read_text(encoding="utf-8")


@pytest.mark.parametrize("response", ["success", "unicode", "large"])
def test_native_response_bytes_and_existing_capture_are_preserved(
    collector, fake_iem, response
):
    call, _, _, capture = collector
    prefix = b'<?xml version="1.0"?><BESAPI><Query><Result><Answer type="string">Existing answer</Answer></Result></Query></BESAPI>\n'
    capture.write_bytes(prefix)
    expected = subprocess.check_output(
        [str(fake_iem), "GET", "query", "--relevance=" + response]
    )
    assert call("Request", response) == 0
    assert capture.read_bytes() == prefix + expected + b"\n"


CONTEXT_WRAPPER = r"""
param($Helper, $ArgumentsFile, $HardwareMode)
function Get-CimInstance {
    param($ClassName, $Property, $OperationTimeoutSec, $ErrorAction)
    if ($HardwareMode -eq 'Unavailable') { throw 'PRIVATE_EXCEPTION PRIVATE_HOST' }
    switch ($ClassName) {
        'Win32_ComputerSystem' { [pscustomobject]@{ Manufacturer='Lab vendor'; Model='Lab VM'; TotalPhysicalMemory=68719476736; Name='PRIVATE_HOST'; SerialNumber='PRIVATE_SERIAL' } }
        'Win32_Processor' {
            [pscustomobject]@{ Name='Lab CPU'; NumberOfCores=8; NumberOfLogicalProcessors=16; ProcessorId='PRIVATE_CPU_ID' }
            [pscustomobject]@{ Name='Lab CPU'; NumberOfCores=8; NumberOfLogicalProcessors=16; ProcessorId='PRIVATE_CPU_ID' }
        }
        'Win32_OperatingSystem' { [pscustomobject]@{ Caption='Lab OS'; Version='10.0.12345'; OSArchitecture='64-bit'; RegisteredUser='PRIVATE_OWNER' } }
        default { throw 'Unexpected CIM class' }
    }
}
$bound = @{}
(Get-Content -LiteralPath $ArgumentsFile -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $bound[$_.Name] = $_.Value }
& $Helper @bound
exit $LASTEXITCODE
"""


@pytest.fixture
def context_collector(tmp_path, fake_iem):
    wrapper = tmp_path / "context-wrapper.ps1"
    wrapper.write_text(CONTEXT_WRAPPER, encoding="utf-8")
    sequence = 0

    def create(
        *,
        hardware="Available",
        selected="General=true;Root=true",
        logs="0",
        task_type="Standalone",
        other_modules="",
    ):
        nonlocal sequence
        sequence += 1
        directory = tmp_path / str(sequence)
        directory.mkdir()
        state = directory / "state.json"
        csv_path = directory / "diagnostics.csv"
        capture = directory / "General_Info_PRIVATE_HOST.xml"
        summary = directory / "state_Summary.txt"
        arguments_file = directory / "arguments.json"

        def call(mode, response=None, *, number=1):
            arguments = {
                "Mode": mode,
                "StateFile": str(state),
                "CsvFile": str(csv_path),
                "Capture": str(capture),
            }
            if mode == "Init":
                arguments.update(
                    SelectedSections=selected,
                    PauseSeconds=5,
                    DataLogs=logs,
                    ClientVersion="11.0.test",
                    TaskType=task_type,
                    OtherModules=other_modules,
                )
            if response:
                arguments.update(
                    IemPath=str(fake_iem),
                    Resource="query",
                    EncodedRelevance=response,
                    QueryNumber=number,
                )
            arguments_file.write_text(json.dumps(arguments), encoding="utf-8")
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(wrapper),
                    str(HELPER),
                    str(arguments_file),
                    hardware,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert not result.stdout and not result.stderr, (result.stdout, result.stderr)
            return result.returncode

        assert call("Init") == 0
        return call, state, summary, capture

    return create


def test_context_reuses_only_successful_aggregate_answers_and_preserves_zero(
    context_collector,
):
    call, state, summary, capture = context_collector()
    for number, response in (
        (14, "nodes"),
        (16, "zero-relays"),
        (15, "active-nodes"),
        (20, "server-versions"),
        (30, "blank-versions"),
        (33, "server-cpu"),
        (34, "server-ram"),
        (35, "server-os"),
        (3, "license-secret"),
        (36, "hardware-secret"),
    ):
        assert call("Request", response, number=number) == 0
    assert call("Finish") == 0
    data = json.loads(state.read_text())
    environment = data["Environment"]
    assert environment["Deployment"]["ComputerCount"] == 42
    assert environment["Deployment"]["RelayCount"] == 0
    assert environment["Deployment"]["ActiveComputerCount"] == 32
    assert environment["Deployment"]["ServerVersionCounts"] == "11.0.6--2"
    assert environment["Sources"]["ServerVersionCounts"] == "DI-020"
    assert environment["Deployment"]["RootServersReportedRam"] == "64 GB"
    assert environment["Sources"]["ComputerCount"] == "DI-014"
    local = environment["LocalRootHardware"]
    assert (local["CpuSockets"], local["CpuCores"], local["LogicalProcessors"]) == (
        2,
        16,
        32,
    )
    assert local["OsReportedMemoryGiB"] == 64
    assert local["CpuModel"] == "Lab CPU"
    assert data["Run"]["PlannedRequests"] == 34
    assert "RelayCount: 0; source: DI-016" in summary.read_text()
    assert "ActiveComputerCount: 32" in summary.read_text()
    for text in (state.read_text(), summary.read_text()):
        for private in (
            "PRIVATE_HOST",
            "PRIVATE_SERIAL",
            "PRIVATE_CPU_ID",
            "PRIVATE_OWNER",
            "PRIVATE_LICENSE",
            "PRIVATE_HARDWARE",
            "PRIVATE_METRIC",
        ):
            assert private not in text
    assert "PRIVATE_LICENSE" in capture.read_text()
    assert "PRIVATE_HARDWARE" in capture.read_text()


@pytest.mark.parametrize("response", ["partial-nodes", "empty", "forbidden"])
def test_missing_or_failed_node_answers_do_not_become_zero(context_collector, response):
    call, state, summary, _ = context_collector()
    assert call("Request", response, number=14) == 0
    expected = 0 if response == "empty" else 24004
    assert call("Finish") == expected
    data = json.loads(state.read_text())
    assert data["Environment"]["Deployment"]["ComputerCount"] is None
    assert "ComputerCount: Unavailable" in summary.read_text()
    assert data["Run"]["Status"] == ("Completed" if expected == 0 else "Incomplete")


def test_unavailable_local_context_does_not_fail_collection(context_collector):
    call, state, summary, _ = context_collector(
        hardware="Unavailable", selected="Root=true"
    )
    assert call("Request", "success", number=29) == 0
    assert call("Finish") == 0
    data = json.loads(state.read_text())
    assert data["Errors"] == 0
    assert data["Run"]["SelectedSections"] == ["Root"]
    assert data["Run"]["PlannedRequests"] == 8
    assert len(data["Environment"]["DiscoveryWarnings"]) == 3
    assert all(
        value is None for value in data["Environment"]["LocalRootHardware"].values()
    )
    assert "PRIVATE_EXCEPTION" not in summary.read_text()
    assert "Local computer hardware unavailable" in summary.read_text()


def test_readable_summary_has_bounded_slowest_requests_and_distinct_timings(
    context_collector,
):
    call, state, summary, _ = context_collector(logs="1")
    running = summary.read_text()
    assert "Status: Running" in running and "Completion has not been confirmed" in running
    for number in range(1, 12):
        assert call("Request", "slow" if number == 4 else "success", number=number) == 0
    assert call("Request", "query-error", number=12) == 0
    assert call("Finish") == 24004
    data = json.loads(state.read_text())
    run = data["Run"]
    assert run["PlannedRequests"] == 36  # The two optional admin calls.
    assert run["PausesScheduled"] == data["Requests"] == 12
    assert run["ElapsedMs"] >= run["RequestWallTimeMs"] > run["ServerEvaluationMs"]
    assert run["ParsedEvaluationCount"] == 11
    assert run["ServerEvaluationMs"] == 2.75
    assert run["EndedUtc"] and run["Status"] == "Incomplete"
    assert len(run["SlowestRequests"]) == 10
    # Compare with measured CSV durations; process startup can exceed the fake delay.
    with (state.parent / "diagnostics.csv").open(encoding="utf-8-sig") as stream:
        measured = {
            row["QueryId"]: int(row["WallTimeMs"])
            for row in csv.DictReader(stream)
            if row["Resource"] == "query"
        }
    assert [item["WallTimeMs"] for item in run["SlowestRequests"]] == sorted(
        measured.values(), reverse=True
    )[:10]
    assert all(
        measured[item["QueryId"]] == item["WallTimeMs"] for item in run["SlowestRequests"]
    )
    assert run["Sections"]["General"]["Failures"] == 1
    assert run["FailureExamples"][0]["QueryId"] == "DI-012"
    text = summary.read_text()
    assert "estimated scheduled pacing" in text
    assert "not a measured delay" in text
    assert "Request wall time includes CLI execution" in text
    assert "not end-to-end request time" in text
    assert "DI-012 | General | QueryFailure" in text
    assert len(run["HelperSha256"]) == len(run["QueryContractSha256"]) == 64
    assert (
        run["HelperSha256"]
        == hashlib.sha256(HELPER.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    )


@pytest.mark.parametrize(
    "response,expected,parsed,unparsed", [("seconds", 500, 1, 0), ("no-unit", 0, 0, 1)]
)
def test_server_evaluation_units_are_explicit(
    context_collector, response, expected, parsed, unparsed
):
    call, state, _, _ = context_collector()
    assert call("Request", response) == 0
    assert call("Finish") == 0
    run = json.loads(state.read_text())["Run"]
    assert run["ServerEvaluationMs"] == expected
    assert run["ParsedEvaluationCount"] == parsed
    assert run["UnparsedEvaluationCount"] == unparsed


@pytest.mark.parametrize("logs,expected", [("0", 177), ("1", 179)])
def test_complete_plan_includes_only_selected_admin_requests(
    context_collector, logs, expected
):
    selected = ";".join(
        f"{section}=true"
        for section in (
            "General",
            "Root",
            "Relays",
            "RelayAffiliation",
            "Clients",
            "ClientSettings",
            "Operators",
            "Content",
            "Properties",
            "Actions",
        )
    )
    call, state, _, _ = context_collector(selected=selected, logs=logs)
    assert call("Finish") == 0
    assert json.loads(state.read_text())["Run"]["PlannedRequests"] == expected


def test_combined_request_window_starts_after_initialization(context_collector):
    call, state, summary, _ = context_collector(
        task_type="Day1", other_modules="Overview=true;HealthDashboard=false"
    )
    initial = json.loads(state.read_text())["Run"]
    assert initial["FirstRequestUtc"] is None
    assert initial["RequestWindowMs"] is None
    assert initial["OtherSelectedModules"] == ["Overview"]
    assert call("Request", "success") == 0
    assert call("Finish") == 0
    run = json.loads(state.read_text())["Run"]
    assert run["FirstRequestUtc"]
    assert run["ElapsedMs"] > run["RequestWindowMs"] >= run["RequestWallTimeMs"]
    assert "Other selected Day 1 modules: Overview" in summary.read_text()
    assert (
        "excludes earlier initialization/login/dashboard modules" in summary.read_text()
    )
