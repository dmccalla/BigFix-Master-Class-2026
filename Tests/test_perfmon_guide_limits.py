# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

"""PerfMon applies only the NFR guide's limits. There are no warning levels."""

from __future__ import annotations

import get_perfmon_charts as perfmon
import pytest


@pytest.mark.parametrize(
    "counter,inside,over",
    [
        ("Processor_Total_Processor_Time", 75, 81),
        ("Processor_Total_Privileged_Time", 9, 11),
        ("System_Processor_Queue_Length", 3.5, 5),
    ],
)
def test_values_under_the_guide_limit_pass(
    counter: str, inside: float, over: float
) -> None:
    threshold = perfmon.get_threshold(counter, 16, 1, False)

    assert threshold["warn"] is None
    assert perfmon.sample_status(inside, threshold) == "OK"
    assert perfmon.sample_status(over, threshold) == "Critical"


def test_page_file_has_no_warning_level() -> None:
    threshold = perfmon.get_threshold("Paging_File_Total_Usage_Peak", 16, 1, False)

    assert threshold["warn"] is None
    assert perfmon.sample_status(4.5, threshold) == "OK"
