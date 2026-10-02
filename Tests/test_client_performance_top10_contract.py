# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# BigFix Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Contracts for the client-performance Top 10 collection relevance."""

from __future__ import annotations

from pathlib import Path

import pytest
from defusedxml import ElementTree as ET

PROJECT = Path(__file__).resolve().parents[1]
ANALYSIS_TITLE = "BigFix Master Class -- Client Performance Counters - Basic (2.0)"
SOURCES = (
    PROJECT / "Utilities" / "query_properties.ps1",
    PROJECT
    / "Tasks and Analyses"
    / "Individual Tasks"
    / "BigFix Master Class -- Collect Client Performance Counter Analysis Data (2.0).bes",
)


def _top10_template(source: Path) -> str:
    if source.suffix.lower() == ".ps1":
        script = source.read_text(encoding="utf-8")
    else:
        action = ET.parse(source).getroot().find(".//ActionScript")
        assert action is not None
        script = action.text or ""

    return next(
        line for line in script.splitlines() if line.startswith("$Top10Template =")
    )


@pytest.mark.parametrize("source", SOURCES, ids=lambda path: path.name)
def test_top10_capture_selects_only_its_own_analysis(source: Path) -> None:
    template = _top10_template(source)

    assert "elements of set of bes properties whose" in template
    assert f'name of source analysis of it = "{ANALYSIS_TITLE}"' in template
    assert "bes property whose" not in template
