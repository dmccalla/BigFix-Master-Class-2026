# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""The status spine -- the report's ONE status vocabulary, defined once.

Every status signal in the report -- per check, per category, overall, in a
chart or in prose -- uses these five levels and no others. This module is the
single source of truth: scoring reads its bands, the charts read its palette
(injected as ``window.SPINE``), and the design system mirrors its hexes. New
work references this instead of hardcoding a color or word, so nothing can drift
back to the four retired vocabularies (OK/Warning, Healthy/Attention, the
Olympic medals, PASS/ADVISORY/FAIL) by construction. The guard test
``tests/test_status_spine_invariants.py`` fails loud if a retired token sneaks
back in anyway.

  Level            Mark      Text      Band       Per-check
  Healthy          #187A43   #187A43   85-100     Pass
  Advisory         #2A6FDB   #2A6FDB   (info)     Advisory
  Needs Attention  #B45309   #B45309   60-84      (rolls up from Fails)
  Critical         #C2410C   #C2410C   0-59       Fail
  Not Assessed     #0B1640   #0B1640   excluded   Cannot Verify

``mark`` is the canonical spine color (dots, bars, chips, swatches). ``text`` is
the AA-legible companion for small status text. Marks also clear the WCAG
non-text 3:1 target against the report's white/light surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpineLevel:
    word: str
    mark: str  # canonical status hex: dots / bars / chips / swatches
    text: str  # AA-legible companion hex for small status text
    bg: str  # soft tint behind pills/marks
    low: int | None  # score-band lower bound (None = not score-driven)
    high: int | None
    per_check: str  # the matching per-check result term


HEALTHY = SpineLevel("Healthy", "#187A43", "#187A43", "#D5F5E3", 85, 100, "Pass")
ADVISORY = SpineLevel("Advisory", "#2A6FDB", "#2A6FDB", "#E6EFFD", None, None, "Advisory")
NEEDS_ATTENTION = SpineLevel(
    "Needs Attention", "#B45309", "#B45309", "#FFF8E7", 60, 84, "Fail (rolled up)"
)
CRITICAL = SpineLevel("Critical", "#C2410C", "#C2410C", "#FDECEA", 0, 59, "Fail")
NOT_ASSESSED = SpineLevel(
    "Not Assessed", "#0B1640", "#0B1640", "#F0F2F5", None, None, "Cannot Verify"
)

LEVELS: tuple[SpineLevel, ...] = (
    HEALTHY,
    ADVISORY,
    NEEDS_ATTENTION,
    CRITICAL,
    NOT_ASSESSED,
)
BY_WORD: dict[str, SpineLevel] = {level.word: level for level in LEVELS}

NOT_ASSESSED_WORD = NOT_ASSESSED.word


def _score_low(level: SpineLevel) -> int:
    """Return the required lower bound for a score-driven spine level."""
    if level.low is None:
        raise ValueError(f"{level.word} is not a score-driven spine level")
    return level.low


# Score-driven bands only (Advisory is informational, never a score band; Not
# Assessed is excluded), worst-to-best for rating_for_score.
_SCORE_LEVELS = sorted((HEALTHY, NEEDS_ATTENTION, CRITICAL), key=_score_low, reverse=True)
RATING_SCALE: list[tuple[int, str]] = [
    (_score_low(level), level.word) for level in _SCORE_LEVELS
]


def rating_for_score(score) -> str:
    """Map a 0-100 score (or None) to its spine word. None = Not Assessed --
    never a Critical zero."""
    if score is None:
        return NOT_ASSESSED_WORD
    for low, word in RATING_SCALE:
        if score >= low:
            return word
    return CRITICAL.word


def band_label(word: str) -> str:
    """Human band string for a spine word, e.g. 'Healthy' -> '85-100'. Empty for
    levels with no score band (Advisory, Not Assessed)."""
    level = BY_WORD.get(word)
    if not level or level.low is None:
        return ""
    return f"{level.low}-{level.high}"


def chart_palette() -> dict[str, dict[str, str]]:
    """The spine as a JSON-able dict for injection into the chart template
    (``window.SPINE``). The chart engine reads its status colors from this, so
    one edit here re-themes every chart -- the same way the design owns layout."""
    return {
        level.word: {
            "mark": level.mark,
            "text": level.text,
            "bg": level.bg,
            "band": (f"{level.low} to {level.high}" if level.low is not None else ""),
        }
        for level in LEVELS
    }
