# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""FillDB wording from Design's 10-20 change list, Section 6 (FD-05 to FD-10)."""

from __future__ import annotations

import get_filldb_performance as filldb


def _row(name: str, health: str, time_ms: str = "100") -> dict[str, str]:
    return {
        "FillDB Object": f"{name}:",
        "Count": "10",
        "Time (ms)": time_ms,
        "Rate/s": "1",
        "Health Check": health,
    }


GUIDE = [
    _row("Parallel DB Update (Short Batch)", "988%: Great", "3031912"),
    _row("Parallel DB Update", "----: Not enough data."),
    _row("Batch Rate", "988%: Great", "3031912"),
    _row("Parallel Parsing", "236%: Great"),
]


def test_object_health_sample() -> None:
    rows = [
        *GUIDE,
        _row("Fixlet results", "093%: Good"),
        _row("Computer administrators", "004%: Poor"),
        _row("Computer relay statuses", "----: Not enough data."),
    ]
    assert filldb.object_health_paragraph(rows) == (
        "The analyzer rates 3 objects Great, 1 Good and 1 Poor. 2 objects could not be rated. Parallel DB Update (10 rows) and Computer Relay Statuses (10 rows) had too little data. Parallel DB Update "
        "(Short Batch) takes the most time at 3031912 ms. The score covers 3 of the "
        "4 guide checks. Parallel DB Update had too little data. The "
        "Workload by Object chart above shows the time for every object."
    )


def test_object_health_leaves_out_zero_parts() -> None:
    rows = [_row(name, "200%: Great") for name in filldb.GUIDE_CHECKS]
    text = filldb.object_health_paragraph(rows)
    assert text.startswith("The analyzer rates 4 objects Great. ")
    assert "too little data" not in text
    assert "Poor" not in text
    assert "The score covers the 4 guide checks." in text


def test_object_health_names_no_poor_object() -> None:
    """Design, 10-21: the counts stay, and no object is named as Poor."""
    rows = [
        *GUIDE,
        _row("Computer administrators", "004%: Poor"),
        _row("Computer roles", "010%: Poor"),
        _row("Fixlet results", "002%: Poor"),
    ]
    text = filldb.object_health_paragraph(rows)
    assert "3 Poor" in text
    assert "is Poor" not in text and "are Poor" not in text
    for name in ("Computer Administrators", "Computer Roles", "Fixlet Results"):
        assert name not in text
    assert "1 object could not be rated." in text


def test_title_paragraph() -> None:
    rows = [*GUIDE, {"FillDB Object": "Lines processed", "Count": "4237218"}]
    metadata = {"start": "11-16-2025 02:56", "end": "11-17-2025 15:57"}
    title = filldb.filldb_title_paragraph(rows, metadata)
    assert title == (
        "This analysis covers a FillDB capture from 11-16-2025 02:56 to "
        "11-17-2025 15:57. The analyzer processed 4237218 lines."
    )
    assert "Excel" not in title and "CSV" not in title


def test_score_text_uses_ranges_not_bands() -> None:
    source = filldb.Path(filldb.__file__).read_text(encoding="utf-8")
    assert "Score bands" not in source
    assert "Score ranges: 90 to 100 Healthy, 70 to 89 Needs Attention, 0 to 69 " in source
