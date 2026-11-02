# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

"""FillDB scores the four checks NFR PRF-BIG-30 names (version 11.x.4, p25)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import get_filldb_performance as filldb
import pytest

from Lib.Analysis import filldb_perf_log


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


@pytest.mark.parametrize(
    ("ratings", "score", "status", "assessed"),
    [
        (("Great", "Good", "Great", "Good"), 100, "Healthy", 4),
        (("Good", "Good", "Great", "Poor"), 75, "Needs Attention", 4),
        (("Good", "Poor", "Great", "Poor"), 50, "Critical", 4),
        (("Poor", "Poor", "Poor", "Poor"), 0, "Critical", 4),
        (("Great", "Unknown", "Good", "----: Not enough data."), 100, "Healthy", 2),
        (("Good", "Unknown", "Poor", "----: Not enough data."), 50, "Critical", 2),
        (
            ("Unknown", "", "----: Not enough data.", "Unknown"),
            "N/A",
            "Not Assessed",
            0,
        ),
    ],
)
def test_filldb_score_uses_only_assessed_guide_checks(
    tmp_path, monkeypatch, ratings, score, status, assessed
) -> None:
    """Known scores cover missing data, failed checks and unrelated good data."""
    from Lib.Design import html_charts

    captured = {}
    monkeypatch.setattr(
        html_charts, "render_chart", lambda _kind, data, _path: captured.update(data)
    )
    rows = [_row(name, rating) for name, rating in zip(filldb.GUIDE_CHECKS, ratings)]
    # Context objects must neither rescue missing guide data nor lower its score.
    rows += [_row("Fixlet Results", "Great"), _row("Computer Administrators", "Poor")]
    filldb.generate_filldb_chart(rows, tmp_path / "unused.png", {})
    assert captured["score"] == score
    assert captured["status"]["label"] == status
    assert f"{assessed} were assessed" in captured["scopeNote"]
    assert bool(captured["assessmentNote"]) == (assessed == 0)


@pytest.mark.skipif(
    sys.platform != "win32" or filldb_perf_log.analyzer_exe_path() is None,
    reason="Requires the bundled Windows FillDB analyzer",
)
@pytest.mark.parametrize(
    ("events", "messages", "elapsed_ms", "expected"),
    [
        (100, 1, 1000, "unknown"),
        (100, 1000, 1000, "great"),
        (100, 1000, 100000, "poor"),
    ],
)
def test_real_analyzer_distinguishes_sparse_healthy_and_poor_captures(
    tmp_path, events, messages, elapsed_ms, expected
) -> None:
    """Synthetic raw controls test the actual executable, without replacing ratings."""
    start = datetime(2026, 11, 2, 10, tzinfo=timezone(timedelta(hours=-5)))
    lines = [
        f"{start:%a, %d %b %Y %H:%M:%S %z} -- 1 -- FillDB parallelism enabled for normal reports, with the following parameters:",
        "Parsing Threads:                        3",
        "DB Threads:                             3",
    ]
    for index in range(events):
        timestamp = start + timedelta(seconds=index * 120)
        # Include normal mapping work, as a real capture does. Tiny six-line
        # inputs hit the external analyzer's rounded-zero processing-time bug.
        lines.extend(
            f"{timestamp:%a, %d %b %Y %H:%M:%S %z} -- 1 -- GetReservedPropertyMap: 1 ms"
            for _ in range(100)
        )
        for name in (
            "Parallel Parsing",
            "Parallel DB Update (Short Batch)",
            "Parallel DB Update",
        ):
            lines.append(
                f"{timestamp:%a, %d %b %Y %H:%M:%S %z} -- 1 -- ----------- {name}: "
                f"{messages} messages in {elapsed_ms} ms: "
                f"{messages * 1000 // elapsed_ms} messages/sec"
            )
    raw = tmp_path / "synthetic-control.log"
    raw.write_text("\n".join(lines) + "\n", encoding="utf-8")
    analyzed = filldb_perf_log.ensure_analysis_csv(
        raw, dest_csv=tmp_path / "analysis.csv"
    )
    rows = [
        row for row in filldb.parse_filldb_csv(analyzed) if filldb.is_guide_check(row)
    ]
    assert len(rows) == 4
    assert {filldb.health_status(row["Health Check"]) for row in rows} == {expected}
    assert next(row for row in rows if row["FillDB Object"] == "Parallel Parsing:")[
        "Count"
    ] == str(events * messages)
