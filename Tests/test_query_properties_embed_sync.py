# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# BigFix Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Keep the standalone query_properties.ps1 and the task's embedded copy identical."""

from __future__ import annotations

import csv
import shutil
import subprocess
from pathlib import Path

import pytest
from defusedxml import ElementTree as ET

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
PROJECT = Path(__file__).resolve().parents[1]
UTILITY = PROJECT / "Utilities" / "query_properties.ps1"
TASK = (
    PROJECT
    / "Tasks and Analyses"
    / "Individual Tasks"
    / "BigFix Master Class -- Collect Client Performance Counter Analysis Data (2.0).bes"
)
SAMPLE = PROJECT / "SampleData" / "BigFix Master Class 2026" / "Results" / "Client_Loop"


def _embedded() -> str:
    action = ET.parse(TASK).getroot().find(".//ActionScript")
    assert action is not None
    text = action.text or ""
    start = text.index("# query_properties.ps1")
    return text[start : text.index("\n__END__", start)].strip()


def _utility() -> str:
    text = UTILITY.read_text(encoding="utf-8")
    return text[text.index("# query_properties.ps1") :].strip()


def test_task_embeds_the_standalone_utility() -> None:
    # ActionScript unescapes only "{{". A doubled "}" reaches the client as
    # "}}" and PowerShell cannot parse the script.
    assert _embedded() == _utility().replace("{", "{{")


def _rows(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is not available")
@pytest.mark.skipif(
    not (SAMPLE / "Client_Loop_10-06-2026_2130.xml").exists(),
    reason="The class sample capture is not tracked, so check it when present",
)
def test_standalone_reproduces_the_server_csvs_from_the_sample(tmp_path: Path) -> None:
    loop_csv = tmp_path / "loop.csv"
    udp_csv = tmp_path / "udp.csv"
    result = subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(UTILITY),
            "-LoopXml",
            str(SAMPLE / "Client_Loop_10-06-2026_2130.xml"),
            "-UdpXml",
            str(SAMPLE / "UDP_Notifications_10-06-2026_2130.xml"),
            "-OutputLoopCsv",
            str(loop_csv),
            "-OutputUdpCsv",
            str(udp_csv),
            "-OutputTop10Csv",
            str(tmp_path / "top10.csv"),
            "-LogFile",
            str(tmp_path / "query_properties.log"),
            "-Quiet",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert _rows(loop_csv) == _rows(SAMPLE / "Client_Loop_10-06-2026_2130.csv")
    assert _rows(udp_csv) == _rows(SAMPLE / "udp-notification-results.csv")
