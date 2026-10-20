# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

"""PerfMon observations say sustained only when most readings were over."""

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


def test_a_short_run_of_readings_is_not_called_sustained() -> None:
    text = perfmon.observation_for_findings("Storage Latency", [_finding(4)])[
        "observation"
    ]

    assert "sustained" not in text
    assert "4 of 59 readings (6.78%) were over the limit" in text
    assert "They raised the average over the limit. The other 55 readings met" in text
    assert " -- " not in text


def test_most_readings_over_reads_as_sustained() -> None:
    text = perfmon.observation_for_findings("CPU Privileged Time", [_finding(54)])[
        "observation"
    ]

    assert "The average stayed over the limit for most of the capture." in text
