# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
"""Execute the real diagnostic helper with a local fake IEM binary, without a server."""

from __future__ import annotations

import csv
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
        string kind = args[args.Length - 1].Replace("--relevance=", "");
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
        if (kind == "unicode") {
            Console.WriteLine("<?xml version=\"1.0\" encoding=\"UTF-8\"?><BESAPI><Query><Result><Answer type=\"string\">Caf\u00e9 \u5ba2\u6237 &amp; value</Answer></Result></Query></BESAPI>"); return 0;
        }
        if (kind == "large") {
            Console.WriteLine("<?xml version=\"1.0\" encoding=\"UTF-8\"?><BESAPI><Query><Result><Answer type=\"string\">" + new string('x', 2000000) + "</Answer></Result></Query></BESAPI>"); return 0;
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


def test_permission_and_query_errors_continue_then_report_incomplete(collector):
    call, state, _, capture = collector
    assert call("Request", "forbidden") == 0
    assert call("Request", "query-error") == 0
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
