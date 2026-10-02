# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""PRF-INF-09 scores page file use as a percent of physical memory.

The NFR guide sets the limit at 5% of physical memory. Paging File % Usage
Peak is a percent of the page file, so the Workbench converts it with the
Memory Commit Limit counter. Without physical memory the counter is not scored.
"""

from __future__ import annotations

import get_perfmon_charts as perfmon
import pandas as pd
import pytest

GIB = 1024**3
USAGE = "Paging_File_Total_Usage_Peak"
COMMIT = "Memory_Commit_Limit"


def _frame(usage: list, commit: list | None) -> pd.DataFrame:
    data = {
        "Sample": range(1, len(usage) + 1),
        "Time": pd.date_range("2026-06-14 20:00", periods=len(usage), freq="min"),
        USAGE: usage,
    }
    if commit is not None:
        data[COMMIT] = commit
    return pd.DataFrame(data)


def _analyze(df: pd.DataFrame, memory_gb: int) -> dict:
    _chart, findings = perfmon.analyze(
        df,
        [USAGE],
        memory_gb,
        0,
        False,
        10,
        0.98,
        1.15,
        "06-14-2026 20:00",
        "06-14-2026 20:03",
        "Parameter Supplied" if memory_gb else "Not supplied",
        "Not supplied",
        "Not supplied",
    )
    return next(item for item in findings if item["Counter"] == USAGE)


def test_page_file_use_is_converted_to_a_percent_of_physical_memory() -> None:
    # 16 GiB commit limit and 12 GiB of RAM leave a 4 GiB page file. Half of it
    # in use is 2 GiB, which is 16.67% of physical memory.
    result = perfmon.page_file_percent_of_memory(
        pd.Series([50.0]), pd.Series([16 * GIB]), 12
    )
    assert result.iloc[0] == pytest.approx(2 / 12 * 100)


def test_scored_counter_uses_the_physical_memory_basis() -> None:
    finding = _analyze(_frame([3.0, 3.0, 3.0], [16 * GIB] * 3), 12)

    assert finding["Status"] == "OK"
    assert finding["Average"] == pytest.approx(1.0)
    assert not finding.get("NotScoredReason")
    assert "physical memory" in finding["Threshold"]


def test_counter_is_not_scored_without_physical_memory() -> None:
    finding = _analyze(_frame([47.0, 47.0, 47.0], [16 * GIB] * 3), 0)

    assert finding["Status"] == "Not Available"
    assert finding["NotScoredReason"] == perfmon.MEMORY_NOT_SUPPLIED
    assert finding["PeakViolationWindow"] == (
        f"Not scored: {perfmon.MEMORY_NOT_SUPPLIED}"
    )


def test_counter_is_not_scored_without_the_commit_limit_counter() -> None:
    finding = _analyze(_frame([47.0, 47.0, 47.0], None), 12)

    assert finding["Status"] == "Not Available"
    assert finding["NotScoredReason"] == perfmon.COMMIT_LIMIT_MISSING


def test_blank_page_file_counter_still_reports_no_samples() -> None:
    finding = _analyze(_frame([None, None, None], [16 * GIB] * 3), 0)

    assert finding["Status"] == "Not Available"
    assert finding["NotScoredReason"] == ""
    assert finding["PeakViolationWindow"] == "No samples recorded"


def test_not_scored_observation_names_the_reason() -> None:
    finding = _analyze(_frame([47.0, 47.0, 47.0], [16 * GIB] * 3), 0)
    observation = perfmon.observation_for_findings("Memory Health", [finding])

    assert observation["status"] == "Not Available"
    assert perfmon.MEMORY_NOT_SUPPLIED in observation["observation"]
    assert "No samples were recorded" not in observation["observation"]


def test_commit_limit_is_collected_but_never_charted(tmp_path) -> None:
    assert r"\Memory\Commit Limit" in perfmon.COUNTERS

    csv_path = tmp_path / "capture.csv"
    csv_path.write_text(
        '"(PDH-CSV 4.0)","\\\\BFROOT1\\Paging File(_Total)\\% Usage Peak",'
        '"\\\\BFROOT1\\Memory\\Commit Limit"\n'
        f'"06/14/2026 20:17:40.000","47.1","{16 * GIB}"\n',
        encoding="utf-8",
    )
    df, counter_cols = perfmon.load_and_normalize(str(csv_path))

    assert counter_cols == [USAGE]
    assert COMMIT in df.columns
    assert df[COMMIT].iloc[0] == 16 * GIB


def test_not_scored_strip_names_the_reason() -> None:
    message, label, _color = perfmon.zero_counter_strip_text(
        USAGE, False, perfmon.MEMORY_NOT_SUPPLIED
    )
    assert message == f"Not scored: {perfmon.MEMORY_NOT_SUPPLIED}"
    assert label == "CANNOT VERIFY"


def test_scored_observation_keeps_the_physical_memory_basis() -> None:
    finding = _analyze(_frame([47.0, 47.0, 47.0], [16 * GIB] * 3), 12)
    observation = perfmon.observation_for_findings("Memory Health", [finding])

    assert observation["status"] == "Critical"
    assert "<= 5% of physical memory" in observation["observation"]
