# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

"""PerfMon observations report exact counts without estimating duration."""

from __future__ import annotations

import get_perfmon_charts as perfmon


def _finding(violations: int, samples: int = 59) -> dict:
    return {
        "Counter": "LogicalDisk_C_Avg_Disk_sec_Transfer",
        "Status": "Critical",
        "Threshold": "<= 1ms",
        "Average": 2.05,
        "Maximum": 40.7,
        "Samples": samples,
        "Violations": violations,
        "ViolationPercent": round(violations / samples * 100, 2),
        "PeakViolationWindow": "20:34:40 to 20:40:40",
        "Confidence": "High",
    }


def test_few_readings_are_reported_as_an_exact_count() -> None:
    text = perfmon.observation_for_findings("Storage Latency", [_finding(4)])[
        "observation"
    ]

    assert "sustained" not in text
    assert "4 of 59 readings (6.78%) were over the limit" in text
    assert "Peak: 40.7 ms. Breach window: 20:34:40 to 20:40:40." in text
    assert "The other" not in text
    assert " -- " not in text


def test_most_readings_over_are_reported_as_an_exact_count() -> None:
    text = perfmon.observation_for_findings("CPU Privileged Time", [_finding(54)])[
        "observation"
    ]

    assert "54 of 59 readings (91.5%) were over the limit." in text
    assert "most of the capture" not in text
    assert "Peak: 40.7%." in text


def test_every_reading_over_is_reported_as_an_exact_count() -> None:
    finding = _finding(59)
    original = dict(finding)
    text = perfmon.observation_for_findings("Storage Latency", [finding])["observation"]
    assert "59 of 59 readings (100%) were over the limit." in text
    assert "most of the capture" not in text
    assert finding == original
