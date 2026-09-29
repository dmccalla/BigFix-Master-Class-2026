# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

"""Shortened counter filenames must remain usable by the report injector."""

import fnmatch
from pathlib import Path

import get_perfmon_charts as charts
import inject_perfmon_charts as injector
import pytest


def folder_at_length(tmp_path, length):
    return Path(tmp_path.anchor) / ("d" * (length - len(tmp_path.anchor)))


@pytest.mark.parametrize("suffix", charts._CHART_FILENAME_SUFFIXES)
def test_shortened_names_preserve_metric_and_uniqueness(tmp_path, suffix):
    prefix = "PhysicalDisk_" if "Disk" in suffix else "Counter_"
    folder = folder_at_length(tmp_path, 170)
    first = charts.perfmon_chart_filename(prefix + "a" * 180 + "_" + suffix, folder)
    second = charts.perfmon_chart_filename(prefix + "b" * 180 + "_" + suffix, folder)
    assert first != second
    assert first.endswith(suffix + ".png")
    assert len(str(folder / first)) <= 240
    patterns = [
        pattern for group in injector.SECTION_COUNTER_MAP.values() for pattern in group
    ]
    assert any(fnmatch.fnmatch(first, pattern) for pattern in patterns)


@pytest.mark.parametrize("length", [205, 239, 260])
def test_exhausted_budget_fails_instead_of_losing_metric(tmp_path, length):
    folder = folder_at_length(tmp_path, length)
    with pytest.raises(ValueError, match="Choose a shorter output folder or run name"):
        charts.perfmon_chart_filename(
            "Network_Interface_" + "x" * 160 + "_Packets_Received_Discarded", folder
        )


def test_unshortened_name_is_unchanged(tmp_path):
    folder = folder_at_length(tmp_path, 50)
    assert charts.perfmon_chart_filename("Processor_Total_Processor_Time", folder) == (
        "Processor_Total_Processor_Time.png"
    )
