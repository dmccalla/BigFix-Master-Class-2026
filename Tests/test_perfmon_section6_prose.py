# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""PerfMon wording from Design's 10-20 change list, Section 6, in the forms
approved in PerfMon_FillDB_Prose_Variants_2026-10-20.md."""

from __future__ import annotations

import get_perfmon_charts as charts


def _finding(counter: str, status: str, threshold: str, **values) -> dict:
    finding = {
        "Counter": counter,
        "Status": status,
        "Average": 0,
        "Maximum": 0,
        "Violations": 0,
        "ViolationPercent": 0,
        "Warnings": 0,
        "WarningPercent": 0,
        "Samples": 59,
        "Threshold": threshold,
        "Confidence": "High",
        "PeakViolationWindow": "No threshold breach detected",
    }
    finding.update(values)
    return finding


def _observation(section: str, finding: dict) -> str:
    return charts.observation_for_findings(section, [finding])["observation"]


def test_o3_virtual_machine_cpu_under_the_floor() -> None:
    text = _observation(
        "CPU Utilization",
        _finding(
            "Processor_Total_Processor_Time",
            "Warning",
            "50-80% (VM)",
            Average=40.3,
            Maximum=65.9,
            Warnings=33,
            WarningPercent=55.9,
        ),
    )
    assert text == (
        "The worst counter averaged 40.3%, under the 50% floor of the 50% to 80% "
        "range the guide gives for a virtual machine, so this area is Advisory. It "
        "peaked at 65.9%. 33 of 59 readings (55.9%) were under 50%."
    )


def test_o4_pass_with_readings_over() -> None:
    text = _observation(
        "Storage Queue Depth",
        _finding(
            "PhysicalDisk_Total_Current_Disk_Queue_Length",
            "OK",
            "<= 1 per disk x 1 disks = <= 1",
            Average=0.35,
            Maximum=4.0,
            Violations=4,
            Samples=60,
        ),
    )
    assert text == (
        "The standard was met for this capture window. The worst counter averaged "
        "0.35 against a limit of 1 across 60 readings, with a peak of 4.00. 4 "
        "readings were briefly over the limit, but the average stayed within it."
    )


def test_o5_pass() -> None:
    text = _observation(
        "CPU Utilization",
        _finding(
            "Processor_Total_Processor_Time", "OK", "<= 80%", Average=40.27, Maximum=65.87
        ),
    )
    assert text == (
        "The standard was met for this capture window. The worst counter averaged "
        "40.3% against a limit of 80% across 59 readings, with a peak of 65.9%."
    )


def test_o6_and_o7_network() -> None:
    counter = "Network_Interface_Packets_Received_Errors"
    note = "Packet errors and discards should approach zero per interface"
    assert _observation("Network Health", _finding(counter, "OK", note)) == (
        "No packet errors or discards were added between samples across 59 readings."
    )
    failed = _observation(
        "Network Health",
        _finding(counter, "Critical", note, Average=0.5, Maximum=3, Violations=6),
    )
    assert failed == (
        "The standard was not met for this capture window. Packet errors or "
        "discards were added between samples. The worst counter added 0.50 per "
        "sample on average and peaked at 3.00. 6 of 59 readings showed an increase."
    )


def test_o8_storage_operations() -> None:
    note = "No limit. Reviewed for flat-lining against 5,000 transfers per second."
    text = _observation(
        "Storage Operations",
        _finding(
            "PhysicalDisk_Total_Disk_Transfers_sec",
            "OK",
            note,
            Average=477.6,
            Maximum=1924,
        ),
    )
    assert text == (
        "Context counter with no pass/fail limit. It is scored as Pass. The 5,000 transfers/sec guide value is for reference only. "
        "The highest reading was 1,924 and the average was 478 across 59 readings."
    )


def test_review_summary_forms() -> None:
    ok = _finding("Processor_Total_Processor_Time", "OK", "<= 80%", Average=40)
    advisory = _finding(
        "Processor_Total_Processor_Time", "Warning", "50-80% (VM)", Average=40, Warnings=3
    )
    all_met = charts.build_perfmon_observations([ok, ok], [])["summary"]["lines"][0]
    assert all_met.startswith("All 2 counters reviewed met the standard. The 2 counters ")
    some_advisory = charts.build_perfmon_observations([advisory, ok], [])["summary"][
        "lines"
    ][0]
    assert some_advisory.startswith(
        "Of the 2 counters reviewed, none failed the standard, 1 was Advisory and 1 "
        "met it. The 2 counters roll up into the "
    )


def test_scorecard_tile_and_scoring_line(monkeypatch, tmp_path) -> None:
    import inject_perfmon_charts as inject

    from Lib.Design import html_charts

    captured = {}

    def fake_render(chart, data, output_path):
        captured["data"] = data

    monkeypatch.setattr(html_charts, "render_chart", fake_render)
    observations = {
        "sections": {
            "Storage Operations": {
                "section": "Storage Operations",
                "status": "OK",
                "average": 477.6,
                "threshold": (
                    "No limit. Reviewed for flat-lining against 5,000 transfers per second."
                ),
            }
        }
    }
    inject.render_perfmon_scorecard(observations, tmp_path / "card.png")
    data = captured["data"]
    tile = data["counters"][0]
    assert tile[2] == "~5,000/s"
    assert tile[4] == 8
    assert "scoringLine" not in data
    assert "sourceLine" not in data
