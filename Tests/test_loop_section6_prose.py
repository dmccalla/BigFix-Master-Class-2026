# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Client Performance wording from Design's 10-20 change list, Section 6."""

from __future__ import annotations

from datetime import datetime

import get_loop_health as loop
import pytest

SITE = "Background Evaluation of External Site: Patching Support"
ANALYSIS = "Analysis Name=Application Information (Windows) | Name=Installed Applications"
RETRIEVED = (
    "Retrieved Property: BES Relay Service Installed (actionsite.13:Evaluate Property 1)"
)
OTHER = "Fixlet relevance: Something Else"


def _rows(results: list[str]) -> list[loop.LoopOffenderSummary]:
    return [
        loop.LoopOffenderSummary(
            rank=index + 1,
            occurrences=1,
            total_client_processing_seconds=1.0,
            max_client_processing_seconds=1.0,
            avg_client_processing_seconds=1.0,
            result=result,
        )
        for index, result in enumerate(results)
    ]


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        (
            [SITE] * 8 + [ANALYSIS, RETRIEVED],
            "8 of these 10 are site evaluations. 1 is an analysis property and 1 is "
            "a retrieved property.",
        ),
        (
            [SITE] * 7 + [ANALYSIS] * 2 + [OTHER],
            "7 of these 10 are site evaluations. 2 are analysis properties and 1 is "
            "another evaluation.",
        ),
        (
            [SITE] * 5 + [ANALYSIS] * 3 + [RETRIEVED, OTHER],
            "5 of these 10 are site evaluations. 3 are analysis properties, 1 is a "
            "retrieved property and 1 is another evaluation.",
        ),
        ([SITE] * 10, "10 of these 10 are site evaluations."),
        ([RETRIEVED], "1 of these 1 is a retrieved property."),
    ],
)
def test_top10_kind_sentence_accounts_for_every_row(
    results: list[str], expected: str
) -> None:
    assert loop.top10_kind_sentence(_rows(results)) == expected


def test_generated_date_is_mm_dd_yyyy() -> None:
    stamp = datetime(2026, 10, 2, 9, 5, 7)
    assert f"{stamp:%m-%d-%Y %H:%M:%S}" == "10-02-2026 09:05:07"
    source = (loop.Path(loop.__file__)).read_text(encoding="utf-8")
    assert 'generated_at_text=f"{generated_at:%m-%d-%Y %H:%M:%S}"' in source


def test_mini_report_never_calls_the_loop_groups_bands() -> None:
    source = loop.Path(loop.__file__).read_text(encoding="utf-8")
    assert "points for its band" not in source
    assert "placed in a band" not in source
    assert "band points" not in source
    assert '["Band", "Devices / Total"' not in source


def test_excel_health_summary_calls_the_loop_groups_groups() -> None:
    source = loop.Path(loop.__file__).read_text(encoding="utf-8")
    assert '"Band": "Healthy"' not in source
    assert '"Group": "Healthy"' in source


def test_loop_scoring_line_uses_the_score_points() -> None:
    assert loop.LOOP_SCORING_LINE == (
        "Score ranges: 90 to 100 Healthy, 70 to 89 Warning, 0 to 69 Critical. Points per "
        "device: Healthy 100, Good 85, Warning 67, Critical 34."
    )
