# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Exercise standalone Action Site names alongside analysis-backed Top 10 rows."""

from __future__ import annotations

import csv
import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

import pytest
from defusedxml import ElementTree as ET

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
PROJECT = Path(__file__).resolve().parents[1]
UTILITY = PROJECT / "Utilities" / "query_properties.ps1"
CONTENT_ROOT = PROJECT if (PROJECT / "Tasks and Analyses").exists() else PROJECT.parent


def test_collector_embeds_this_helper() -> None:
    tasks = list(
        (CONTENT_ROOT / "Tasks and Analyses" / "Individual Tasks").glob(
            "*Collect Client Performance Counter Analysis Data (2.0).bes"
        )
    )
    combined = CONTENT_ROOT / "Tasks and Analyses" / "Combined"
    if combined.exists():
        tasks.extend(combined.glob("*Day 4*Client Performance*.bes"))
    assert len(tasks) == (2 if combined.exists() else 1)
    marker = "# query_properties.ps1"
    helper = UTILITY.read_text(encoding="utf-8")
    helper = helper[helper.index(marker) :].strip()
    for task in tasks:
        script = ET.parse(task).getroot().findtext(".//ActionScript") or ""
        embedded = script[
            script.index(marker) : script.index("\n__END__", script.index(marker))
        ].strip()
        assert embedded == helper.replace("{", "{{")


def _capture(*answers: str) -> str:
    content = "".join(f"<Answer>{escape(answer)}</Answer>" for answer in answers)
    return f"<BESAPI><Query><Result>{content}</Result></Query></BESAPI>"


def _run(
    tmp_path: Path, *, property_api_fails: bool = False
) -> tuple[list[dict], list[str]]:
    loop_xml = tmp_path / "loop.xml"
    top10_xml = tmp_path / "top10.xml"
    top10_csv = tmp_path / "top10.csv"
    requests = tmp_path / "requests.txt"
    loop_xml.write_text("<BESAPI/>", encoding="utf-8")
    top10_xml.write_text(
        _capture(
            "10.000: actionsite.18:Evaluate Property 1",
            "6.000: actionsite.18:Evaluate Property 1",
            "5.000: actionsite.6:Evaluate Property 1",
            "4.000: actionsite.999:Evaluate Property 1",
            "2.000: actionsite.77:Evaluate Property 1",
            "7.000: Test Site.44:Evaluate Property 1",
            "3.000: Test Site.44:Background Evaluation",
        ),
        encoding="utf-8",
    )
    property_response = (
        "throw 'Property endpoint unavailable'"
        if property_api_fails
        else """return [pscustomobject]@{Content = '<BESAPI>
            <Property><Name>CPU</Name><ID>6</ID></Property>
            <Property><Name>Client Settings</Name><ID>18</ID></Property>
            </BESAPI>'}"""
    )
    harness = tmp_path / "run.ps1"
    harness.write_text(
        f"""
function Invoke-WebRequest {{
    param([string]$Uri, [hashtable]$Headers, [switch]$UseBasicParsing, [int]$TimeoutSec)
    Add-Content -LiteralPath '{requests.as_posix()}' -Value $Uri
    if ($Uri.EndsWith('/api/properties')) {{ {property_response} }}
    if ($Uri.Contains('/api/query?')) {{
        $relevance = [Uri]::UnescapeDataString(($Uri -split 'relevance=', 2)[1])
        if ($relevance.Contains('id of source analysis of it = 44')) {{
            return [pscustomobject]@{{Content = '<BESAPI><Query><Result><Answer type="string">Analysis Name=Sample Analysis | Display Name=Example Check | Name=Example Check | Source Name=Example Check | Source ID=1</Answer></Result></Query></BESAPI>'}}
        }}
        if ($relevance.Contains('id of source analysis of it = 77')) {{
            return [pscustomobject]@{{Content = '<BESAPI><Query><Result><Answer type="string">Analysis Name=Action Site Analysis | Display Name=Another Check | Name=Another Check | Source Name=Another Check | Source ID=1</Answer></Result></Query></BESAPI>'}}
        }}
        return [pscustomobject]@{{Content = '<BESAPI><Query><Result/></Query></BESAPI>'}}
    }}
    throw "Unexpected API route: $Uri"
}}
& '{UTILITY.as_posix()}' `
    -LoopXml '{loop_xml.as_posix()}' `
    -Top10Input '{top10_xml.as_posix()}' `
    -OutputTop10Csv '{top10_csv.as_posix()}' `
    -OutputUdpCsv '{(tmp_path / "udp.csv").as_posix()}' `
    -ApiQueryUrl 'https://example.invalid/api/query' `
    -BigFixUsername test -BigFixPassword test -QueryAttempts 1 `
    -LogFile '{(tmp_path / "query.log").as_posix()}' -Quiet
exit $LASTEXITCODE
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == (2 if property_api_fails else 0), (
        result.stdout + result.stderr
    )
    with top10_csv.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return rows, requests.read_text(encoding="utf-8").splitlines()


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is not available")
def test_actionsite_properties_resolve_by_rest_id_without_changing_analysis_rows(
    tmp_path: Path,
) -> None:
    rows, requests = _run(tmp_path)
    by_result = {row["Result"]: row for row in rows}
    client_settings = by_result[
        "Retrieved Property: Client Settings (actionsite.18:Evaluate Property 1)"
    ]
    assert client_settings["Status"] == "OK"
    assert client_settings["Occurrences"] == "2"
    assert client_settings["AvgClientProcessingSeconds"] == "8"
    assert client_settings["TotalClientProcessingSeconds"] == "16"
    assert client_settings["MaxClientProcessingSeconds"] == "10"
    assert (
        by_result["Retrieved Property: CPU (actionsite.6:Evaluate Property 1)"]["Status"]
        == "OK"
    )
    assert by_result["actionsite.999:Evaluate Property 1"]["Status"] == "NO RESULTS"
    assert (
        by_result[
            "Analysis Name=Sample Analysis | Display Name=Example Check | Name=Example Check | Source Name=Example Check | Source ID=1"
        ]["Status"]
        == "OK"
    )
    assert (
        by_result[
            "Analysis Name=Action Site Analysis | Display Name=Another Check | Name=Another Check | Source Name=Another Check | Source ID=1"
        ]["Status"]
        == "OK"
    )
    assert (
        by_result["Background Evaluation of External Site: Test Site"]["Status"] == "OK"
    )
    assert sum(route.endswith("/api/properties") for route in requests) == 1
    assert sum("/api/query?" in route for route in requests) == 3


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is not available")
def test_property_api_error_keeps_raw_lookup_and_timing(tmp_path: Path) -> None:
    rows, requests = _run(tmp_path, property_api_fails=True)
    actionsite = [row for row in rows if row["Result"].startswith("actionsite.")]
    assert len(actionsite) == 3
    assert all(row["Status"] == "ERROR" for row in actionsite)
    assert (
        next(row for row in actionsite if row["Result"].startswith("actionsite.18"))[
            "TotalClientProcessingSeconds"
        ]
        == "16"
    )
    assert sum(route.endswith("/api/properties") for route in requests) == 1
