# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

"""FillDB scores the four checks NFR PRF-BIG-30 names (version 11.x.4, p25)."""

from __future__ import annotations

import get_filldb_performance as filldb


def _row(name: str, rating: str) -> dict[str, str]:
    return {
        "FillDB Object": f"{name}:",
        "Count": "10",
        "Time (ms)": "1000",
        "Rate/s": "10",
        "Health Check": rating,
    }


def test_only_the_guide_checks_count() -> None:
    assert filldb.is_guide_check(_row("Batch Rate", "Great"))
    assert filldb.is_guide_check(_row("Parallel DB Update (Short Batch)", "Good"))
    assert not filldb.is_guide_check(_row("computer administrators", "Poor"))
