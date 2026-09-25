# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Guardrail: the report speaks ONE status vocabulary -- the status spine.

Fails loud the moment a retired medal word or a non-spine status color reappears
in the report-rendering code, so new work (human or agent) cannot silently drift
back to the four competing vocabularies (OK/Warning, Healthy/Attention, the
Olympic medals, PASS/ADVISORY/FAIL). The spine is defined once in
``status_spine.py``; this test is the backstop that makes a deviation impossible
to ship quietly. See the 2026 "One Status Vocabulary Across the Whole Report"
design decision.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import status_spine

ROOT = Path(__file__).resolve().parent.parent

# Files that render module output (charts, injectors, design system).
# Excludes: the app UI (chrome, not the output), get_loop_health.py (the spine
# is not applied there), and tests.
_SCAN_GLOBS = (
    "*.py",
    "Get/*.py",
    "Inject/*.py",
    "Assets/chart_template.html",
)
_EXCLUDE_NAMES = {"get_loop_health.py", "diagnostics_workbench_ui.py"}

# Retired Olympic-medal tier names -- no other meaning in this codebase.
_FORBIDDEN_WORDS = ("Platinum", "Gold", "Silver", "Bronze")

# Retired status colors: old green/amber/blue, the metallic medal dots, and the
# FillDB great/good/poor + matplotlib palettes. The brand accent #0F5FDC is NOT
# listed -- it is UI chrome, legitimately non-status. Only spine ``mark`` hexes
# and their AA ``text`` companions are allowed as status colors.
_FORBIDDEN_HEXES = (
    "#1F8A4C",
    "#C77A00",
    "#B26A00",
    "#2E7D32",
    "#1565C0",
    "#C62828",
    "#8C8FB8",
    "#C49A3A",
    "#97A0AA",
    "#B07B4F",
)


def _scan_files() -> list[Path]:
    seen: dict[Path, None] = {}
    for glob in _SCAN_GLOBS:
        for path in ROOT.glob(glob):
            if path.name in _EXCLUDE_NAMES or path.name == Path(__file__).name:
                continue
            seen[path] = None
    return list(seen)


def _hits(token: str, *, word: bool) -> list[str]:
    pattern = re.compile(
        rf"\b{re.escape(token)}\b" if word else re.escape(token), re.IGNORECASE
    )
    out: list[str] = []
    for path in _scan_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for num, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                out.append(f"{path.relative_to(ROOT)}:{num}: {line.strip()[:90]}")
    return out


@pytest.mark.parametrize("medal", _FORBIDDEN_WORDS)
def test_no_retired_medal_word(medal: str) -> None:
    hits = _hits(medal, word=True)
    assert not hits, (
        f"Retired medal tier {medal!r} reappeared. The report uses the status "
        f"spine only (Healthy / Advisory / Needs Attention / Critical / Not "
        f"Assessed) -- see status_spine.py.\n" + "\n".join(hits)
    )


@pytest.mark.parametrize("hexv", _FORBIDDEN_HEXES)
def test_no_retired_status_hex(hexv: str) -> None:
    hits = _hits(hexv, word=False)
    assert not hits, (
        f"Retired status color {hexv} reappeared. Use a spine color from "
        f"status_spine.py (a level's mark/text), not a hardcoded legacy hex.\n"
        + "\n".join(hits)
    )


def test_status_spine_single_source_intact() -> None:
    """Sanity-check the single source itself -- the five levels with their locked
    mark hexes and the score bands -- so a gutted spine is caught too."""
    palette = status_spine.chart_palette()
    assert set(palette) == {
        "Healthy",
        "Advisory",
        "Needs Attention",
        "Critical",
        "Not Assessed",
    }
    assert palette["Healthy"]["mark"] == "#187A43"
    assert palette["Critical"]["mark"] == "#C2410C"
    assert status_spine.rating_for_score(90) == "Healthy"
    assert status_spine.rating_for_score(70) == "Needs Attention"
    assert status_spine.rating_for_score(50) == "Critical"
    assert status_spine.rating_for_score(None) == "Not Assessed"
