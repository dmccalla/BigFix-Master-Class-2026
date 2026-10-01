# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

import pandas as pd
from get_loop_health import (
    convert_to_seconds,
    load_loop_input,
    normalize_loop_time_columns,
    process_rows,
)


def test_numeric_minutes_columns_are_converted_to_hhmmss_before_processing():
    df = pd.DataFrame(
        {
            "Computer Name": ["client-1"],
            "Maximum Cycle Minutes": [90],
            "Average Cycle Minutes": [45],
        }
    )

    normalized = normalize_loop_time_columns(
        df, "Maximum Cycle Minutes", "Average Cycle Minutes"
    )
    processed, not_reported, errors = process_rows(
        normalized,
        "Computer Name",
        "Maximum Cycle Minutes",
        "Average Cycle Minutes",
    )

    assert normalized.loc[0, "Maximum Cycle Minutes"] == "01:30:00"
    assert normalized.loc[0, "Average Cycle Minutes"] == "00:45:00"
    assert processed[0].max_seconds == 5400
    assert processed[0].avg_seconds == 2700
    assert not_reported == 0
    assert errors == 0


def test_numeric_seconds_columns_are_converted_to_hhmmss_before_processing():
    assert convert_to_seconds(3600, "Maximum Cycle Seconds") == 3600

    df = pd.DataFrame(
        {
            "Maximum Cycle Seconds": [3661],
            "Average Cycle Seconds": [61],
        }
    )

    normalized = normalize_loop_time_columns(
        df, "Maximum Cycle Seconds", "Average Cycle Seconds"
    )

    assert normalized.loc[0, "Maximum Cycle Seconds"] == "01:01:01"
    assert normalized.loc[0, "Average Cycle Seconds"] == "00:01:01"


def test_excel_time_fraction_still_converts_to_hhmmss_when_no_unit_hint_exists():
    df = pd.DataFrame(
        {
            "Maximum Loop": [0.5],
            "Average Loop": [0.25],
        }
    )

    normalized = normalize_loop_time_columns(df, "Maximum Loop", "Average Loop")

    assert normalized.loc[0, "Maximum Loop"] == "12:00:00"
    assert normalized.loc[0, "Average Loop"] == "06:00:00"


def test_missing_hour_mmss_strings_are_normalized_to_hhmmss():
    df = pd.DataFrame(
        {
            "Maximum Loop": ["90:30"],
            "Average Loop": ["5:07"],
        }
    )

    normalized = normalize_loop_time_columns(df, "Maximum Loop", "Average Loop")

    assert normalized.loc[0, "Maximum Loop"] == "01:30:30"
    assert normalized.loc[0, "Average Loop"] == "00:05:07"


def test_loop_input_loader_accepts_csv(tmp_path):
    csv_path = tmp_path / "Agent Performance Counters - Basic.csv"
    csv_path.write_text(
        "Computer Name,Maximum Cycle Seconds,Average Cycle Seconds\nclient-1,120,60\n",
        encoding="utf-8",
    )

    df = load_loop_input(csv_path)

    assert list(df.columns) == [
        "Computer Name",
        "Maximum Cycle Seconds",
        "Average Cycle Seconds",
    ]
    assert df.loc[0, "Computer Name"] == "client-1"
    assert df.loc[0, "Maximum Cycle Seconds"] == 120
    assert df.loc[0, "Average Cycle Seconds"] == 60
