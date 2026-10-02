# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# BigFix Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Runtime coverage for client-performance API compatibility failures."""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
from defusedxml import ElementTree as ET

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
PROJECT = Path(__file__).resolve().parents[1]
TASK = (
    PROJECT
    / "Tasks and Analyses"
    / "Individual Tasks"
    / "BigFix Master Class -- Collect Client Performance Counter Analysis Data (2.0).bes"
)
SOURCES = (PROJECT / "Utilities" / "query_properties.ps1", TASK)


def _embedded_script(source: Path) -> str:
    if source.suffix.lower() == ".ps1":
        return source.read_text(encoding="utf-8")

    content = next(iter(ET.parse(source).getroot()))
    action = content.find(".//ActionScript")
    assert action is not None
    action_text = action.text or ""
    start = action_text.index("# query_properties.ps1")
    end = action_text.index("\n__END__", start)
    return action_text[start:end].replace("{{", "{")


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is not available")
@pytest.mark.parametrize("source", SOURCES, ids=lambda path: path.name)
def test_database_compatibility_error_removes_partial_capture(
    source: Path,
    tmp_path: Path,
) -> None:
    script = tmp_path / "query_properties.ps1"
    script.write_text(_embedded_script(source), encoding="utf-8")

    capture_files = [
        tmp_path / "Client_Loop.xml",
        tmp_path / "UDP_Notifications.xml",
        tmp_path / "Top10.xml",
        tmp_path / "Client_Loop.csv",
        tmp_path / "udp-notification-results.csv",
        tmp_path / "top10-query-results.csv",
    ]
    for capture_file in capture_files:
        capture_file.write_text("partial capture", encoding="utf-8")

    log_file = tmp_path / "query_properties.log"
    response = (
        "<BESAPI><Query><Error>Database connection error: Database Error: "
        "The database being connected to has a database version of 'Enterprise 11.113', "
        "and this application requires a database version of 'Enterprise 11.85'."
        "</Error></Query></BESAPI>"
    )
    harness = tmp_path / "compatibility_harness.ps1"
    harness.write_text(
        textwrap.dedent(
            f"""
            function Invoke-WebRequest {{
                param(
                    [string]$Uri,
                    [hashtable]$Headers,
                    [switch]$UseBasicParsing,
                    [int]$TimeoutSec
                )
                $mockResponse = "{response}"
                [pscustomobject]@{{ Content = $mockResponse }}
            }}

            & '{script.as_posix()}' `
                -CaptureLoopXml '{capture_files[0].as_posix()}' `
                -CaptureUdpXml '{capture_files[1].as_posix()}' `
                -CaptureTop10Xml '{capture_files[2].as_posix()}' `
                -OutputLoopCsv '{capture_files[3].as_posix()}' `
                -OutputUdpCsv '{capture_files[4].as_posix()}' `
                -OutputTop10Csv '{capture_files[5].as_posix()}' `
                -ApiQueryUrl 'https://example.invalid/api/query' `
                -BigFixUsername 'test' `
                -BigFixPassword 'test' `
                -LogFile '{log_file.as_posix()}'
            exit $LASTEXITCODE
            """
        ).strip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        check=False,
        capture_output=True,
        text=True,
    )

    command_output = result.stdout + result.stderr
    assert result.returncode == 1, command_output
    assert log_file.exists(), command_output
    log = log_file.read_text(encoding="utf-8")
    assert "BigFix server-side database compatibility error" in log
    assert "No capture files were retained" in log
    assert "Enterprise 11.113" in log
    assert not any(capture_file.exists() for capture_file in capture_files)
