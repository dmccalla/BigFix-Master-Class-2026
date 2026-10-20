# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

"""Four client loop groups: Healthy, Good, Warning and Critical, with edges."""

from __future__ import annotations

from datetime import date, datetime

import get_loop_health as loop
import pandas as pd

HEADERS = [
    "Computer Name",
    "Platform Health Check - Maximum Cycle Minutes",
    "Platform Health Check - Average Cycle Minutes",
]


def _metrics(averages: list[str]):
    frame = pd.DataFrame(
        [[f"QA-{i}", "200", avg] for i, avg in enumerate(averages)], columns=HEADERS
    )
    computer, maximum, average = loop.auto_detect_columns(frame)
    rows, missing, errors = loop.process_rows(frame, computer, maximum, average)
    metrics, _ = loop.calculate_metrics(
        rows,
        len(frame),
        missing,
        errors,
        900,
        3600,
        date(2026, 10, 1),
        date(2026, 10, 2),
        datetime(2026, 10, 3, 12),
        good_threshold_seconds=1800,
    )
    return metrics


def test_each_group_includes_its_lower_edge() -> None:
    metrics = _metrics(["14", "15", "29", "30", "60", "61", "<not reported>"])

    assert metrics.avg_healthy == 1  # 14
    assert metrics.avg_good == 2  # 15 and 29
    assert metrics.avg_warning == 2  # 30 and 60
    assert metrics.avg_over_critical == 1  # 61
    assert metrics.total_issue_count == 1
    assert metrics.avg_critical == 2  # over 60 plus no usable data


def test_option_b_points() -> None:
    every_good = _metrics(["20"] * 4)
    assert every_good.environment_score == 85
    assert every_good.overall_status == "WARNING"

    mixed = _metrics(["10", "20", "40", "<not reported>"])
    assert mixed.environment_score == round((100 + 85 + 67 + 34) / 4)


def test_loop_health_table_has_a_no_usable_data_row() -> None:
    rows = loop.loop_group_rows(_metrics(["10", "20", "40", "90", "<not reported>"]))

    assert [row[0] for row in rows] == [
        "Healthy",
        "Good",
        "Warning",
        "Critical",
        "Critical",
    ]
    assert [row[3] for row in rows] == [
        "< 15 minutes",
        "15-30 minutes",
        "30-60 minutes",
        "> 60 minutes",
        "No usable data",
    ]
