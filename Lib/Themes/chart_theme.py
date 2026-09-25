#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""
chart_theme.py -- shared chart theme.

Single source of truth for fonts, colors, canvas size, status labels, and
common drawing primitives across every chart in the report. New chart
scripts should import `THEME` and the helpers below instead of redefining
their own color constants.

For the prose explanation of WHY each token exists, when to use each
pattern, and what anti-patterns to avoid, see Docs/Reference/Design_Guide.md.

History: promoted from Sandbox/chart_theme_poc/ once the strengths chart
became the second chart to consume it. Older charts (FillDB, Loop Health,
Deployment Overview) still carry duplicated constants and should be
migrated as they're touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from Lib.Design import status_spine
from Lib.Design.design_system import DESIGN_SYSTEM as DS


@dataclass(frozen=True)
class Theme:
    """Shared chart design tokens sourced from the design system."""

    # Font system. Inter is used for ALL chart text and numbers: titles, big
    # KPI numbers, labels, axis ticks, and data figures alike, because it stays
    # legible and column-aligned in dense data at small sizes. Fonts are
    # registered from Fonts/ at import (register_report_fonts) so no OS
    # install is required.
    # Each list is tried in order; the first available font wins.
    font_display_candidates: tuple[str, ...] = (
        "Inter 18pt",
        "Inter",
        "Segoe UI",
        "Arial",
        "DejaVu Sans",
    )
    font_body_candidates: tuple[str, ...] = (
        "Inter 18pt",
        "Inter",
        "Segoe UI",
        "Arial",
        "DejaVu Sans",
    )
    # Cover / title lockup ONLY (not used inside charts).
    font_cover_candidates: tuple[str, ...] = (
        "Inter 18pt",
        "Inter",
        "Segoe UI",
        "Arial",
        "DejaVu Sans",
    )
    # Back-compat: existing charts call choose_font(); the body face is the
    # sensible default for the bulk of chart text.
    font_candidates: tuple[str, ...] = (
        "Inter 18pt",
        "Inter",
        "Segoe UI",
        "Arial",
        "DejaVu Sans",
    )
    dpi: int = 200
    # Canvas presets. tall_figsize is for charts whose role is more
    # qualitative (e.g. trust-building summaries): at 6.5" embed width
    # the result is ~5" tall instead of ~3.9", which gives the section
    # noticeably more presence on the page without breaking from the
    # project's other charts visually.
    wide_figsize: tuple[float, float] = (15.08, 9.08)
    perf_figsize: tuple[float, float] = (14.3, 7.2)
    tall_figsize: tuple[float, float] = (14.0, 10.0)

    # Neutrals from DESIGN_SYSTEM: Tech Grey page, white cards,
    # Midnight text. These values are now unified across all components.
    bg_page: str = DS.tech_grey.hex_value
    bg_card: str = DS.white.hex_value
    title: str = DS.midnight.hex_value
    text: str = DS.midnight.hex_value
    muted: str = "#3E4856"  # darker than DS.text_muted so small chart labels stay legible
    border: str = DS.border_light.hex_value
    track: str = DS.tech_grey.hex_value

    # Status colors stay semantic + WCAG-AA (success is green, not brand teal).
    # All sourced from DESIGN_SYSTEM for consistency.
    pass_color: str = status_spine.HEALTHY.text
    warning_color: str = status_spine.NEEDS_ATTENTION.text
    fail_color: str = status_spine.CRITICAL.text
    cannot_verify_color: str = status_spine.NOT_ASSESSED.text
    # Accents: Accent Blue, Dark Teal, and Software Teal.
    # Purple holds the signature Software Teal -- use it as a fill with dark text.
    blue: str = DS.accent_blue.hex_value
    teal: str = DS.teal_dark.hex_value
    purple: str = DS.software_teal.hex_value

    pass_bg: str = status_spine.HEALTHY.bg
    warning_bg: str = status_spine.NEEDS_ATTENTION.bg
    fail_bg: str = status_spine.CRITICAL.bg
    cannot_verify_bg: str = status_spine.NOT_ASSESSED.bg
    action_bg: str = DS.critical_bg.hex_value

    # Extended handoff tokens: 4-state status marks + neutral chart ink.
    # Color encodes status ONLY; slate/faint/teal_aa are structure.
    healthy: str = status_spine.HEALTHY.mark
    healthy_grad_end: str = DS.success_gradient_end.hex_value
    advisory: str = DS.advisory.hex_value
    advisory_bg: str = DS.advisory_bg.hex_value
    attention_mark: str = status_spine.NEEDS_ATTENTION.mark
    slate: str = DS.slate.hex_value  # neutral workload/volume bars (size, not health)
    faint: str = DS.faint.hex_value  # faint eyebrow/label text
    teal_aa: str = DS.software_teal_aa.hex_value  # eyebrow / section labels


THEME = Theme()


_FONTS_REGISTERED = False


def register_report_fonts() -> None:
    """Register the bundled Inter and Roboto fonts with matplotlib.

    Lets charts use the bundled faces without an OS-level install. Idempotent
    (runs once per process) and best-effort, a missing font dir or a bad file
    is skipped silently so chart generation never fails over typography.
    """
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    _FONTS_REGISTERED = True
    try:
        from matplotlib import font_manager
    except Exception:
        return
    root = Path(__file__).resolve().parents[2]
    for font_dir in (root / "Fonts",):
        if not font_dir.is_dir():
            continue
        for path in font_dir.rglob("*"):
            if path.suffix.lower() in (".otf", ".ttf"):
                try:
                    font_manager.fontManager.addfont(str(path))
                except Exception:
                    continue


def _first_available_font(candidates: tuple[str, ...]) -> str:
    """Return the first registered/installed font from candidates, else last."""
    register_report_fonts()
    try:
        from matplotlib import font_manager
    except Exception:
        return candidates[-1]
    for candidate in candidates:
        try:
            resolved = font_manager.findfont(candidate, fallback_to_default=False)
            # findfont can silently fall back; confirm the family actually matches.
            if (
                candidate.lower()
                in font_manager.FontProperties(fname=resolved).get_name().lower()
            ):
                return candidate
        except (ValueError, RuntimeError):
            continue
    return candidates[-1]


def choose_font(theme: Theme = THEME) -> str:
    """Pick the report BODY font (Inter, then fallbacks).

    Back-compat default for charts that render most of their text as body/data.
    Titles and big KPI numbers should call choose_display_font().
    """
    return _first_available_font(theme.font_body_candidates)


def choose_display_font(theme: Theme = THEME) -> str:
    """Pick the chart DISPLAY font for titles / H1 / big KPI numbers.

    Inter stays legible and column-aligned in dense data at the sizes charts
    shrink to in Word.
    """
    return _first_available_font(theme.font_display_candidates)


def choose_cover_font(theme: Theme = THEME) -> str:
    """Pick the display face for a document cover or title lockup only.

    Not used inside charts, tables, or body text -- those are all Inter.
    """
    return _first_available_font(theme.font_cover_candidates)


def choose_body_font(theme: Theme = THEME) -> str:
    """Explicit alias for the body/data font."""
    return _first_available_font(theme.font_body_candidates)


# 4-state chart status marks (color encodes status ONLY). These are graphical
# marks (bars/dots/fills) so they target WCAG non-text contrast (>=3:1), with
# the official brand hexes. "advisory" is blue, "attention" amber, per the
# design handoff. Use status_color() for small status TEXT (AA >=4.5).
def status_mark(state: str, theme: Theme = THEME) -> str:
    """Return the chart-mark color for a 4-state health value."""
    key = str(state or "").strip().lower()
    return {
        "healthy": theme.healthy,
        "great": theme.healthy,
        "pass": theme.healthy,
        "good": theme.advisory,
        "advisory": theme.advisory,
        "attention": theme.attention_mark,
        "warning": theme.attention_mark,
        "poor": theme.attention_mark,
        "fail": theme.attention_mark,
        "critical": theme.fail_color,
        "nodata": theme.cannot_verify_color,
        "no data": theme.cannot_verify_color,
        "unknown": theme.cannot_verify_color,
    }.get(key, theme.cannot_verify_color)


def status_color(status: str, theme: Theme = THEME) -> str:
    """Return the foreground color for common report statuses."""
    key = str(status or "").strip().upper()
    return {
        "PASS": theme.pass_color,
        "PASSED": theme.pass_color,
        "OK": theme.pass_color,
        "WARNING": theme.warning_color,
        "ADVISORY": theme.warning_color,
        "FAIL": theme.fail_color,
        "FAILED": theme.fail_color,
        "CRITICAL": theme.fail_color,
        "CANNOT VERIFY": theme.cannot_verify_color,
        "NOT AVAILABLE": theme.cannot_verify_color,
    }.get(key, theme.text)


def create_canvas(figsize: tuple[float, float] | None = None, theme: Theme = THEME):
    """Create a standard report canvas and full-page axis."""
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=figsize or theme.wide_figsize, dpi=theme.dpi)
    fig.patch.set_facecolor(theme.bg_page)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    return fig, ax


def add_card(
    ax,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    facecolor: str | None = None,
    edgecolor: str | None = None,
    linewidth: float = 0.8,
    pad: float = 0.003,
    radius: float = 0.008,
    zorder: int = 1,
    theme: Theme = THEME,
):
    """Draw a rounded report card."""
    from matplotlib.patches import FancyBboxPatch

    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad={pad},rounding_size={radius}",
        transform=ax.transAxes,
        facecolor=facecolor or theme.bg_card,
        edgecolor=edgecolor or theme.border,
        linewidth=linewidth,
        zorder=zorder,
    )
    ax.add_patch(patch)
    return patch


def add_text(
    ax,
    x: float,
    y: float,
    text: object,
    *,
    size: float = 14,
    weight: str = "normal",
    color: str | None = None,
    ha: str = "left",
    va: str = "center",
    zorder: int = 4,
    font: str | None = None,
    theme: Theme = THEME,
):
    """Draw theme-aware text."""
    return ax.text(
        x,
        y,
        str(text),
        fontsize=size,
        fontweight=weight,
        color=color or theme.text,
        ha=ha,
        va=va,
        zorder=zorder,
        family=font or choose_font(theme),
    )


def chart_primitives(
    ax,
    *,
    font: str | None = None,
    theme: Theme = THEME,
    default_text_size: float = 14,
):
    """Return chart-bound card/text helpers backed by the shared theme.

    This keeps individual chart scripts from redefining their own low-level
    card and text drawing primitives while still letting them use compact
    local names inside dense layout code.
    """

    def card(
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        fc: str | None = None,
        ec: str | None = None,
        lw: float = 0.8,
        radius: float = 0.008,
        z: int = 1,
    ):
        return add_card(
            ax,
            x,
            y,
            w,
            h,
            facecolor=fc,
            edgecolor=ec,
            linewidth=lw,
            radius=radius,
            zorder=z,
            theme=theme,
        )

    def text(
        x: float,
        y: float,
        value: object,
        *,
        size: float = default_text_size,
        weight: str = "normal",
        color: str | None = None,
        ha: str = "left",
        va: str = "center",
        z: int = 4,
        alpha: float = 1.0,
    ):
        text_obj = add_text(
            ax,
            x,
            y,
            value,
            size=size,
            weight=weight,
            color=color,
            ha=ha,
            va=va,
            zorder=z,
            font=font,
            theme=theme,
        )
        text_obj.set_alpha(alpha)
        return text_obj

    return card, text


def save_png(fig, output_path: str | Path, theme: Theme = THEME) -> Path:
    """Save a themed PNG with standard DPI and page background."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=theme.dpi, facecolor=theme.bg_page)
    return path
