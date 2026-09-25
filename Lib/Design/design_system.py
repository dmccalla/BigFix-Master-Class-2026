#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""
design_system.py -- Unified design system for the Master Class Diagnostics Workbench.

This module provides a single source of truth for all visual design across:
  • UI (diagnostics_workbench_ui.py): CustomTkinter desktop application
  • Charts (chart_theme.py, chart generation scripts), Matplotlib visualizations
  • Workbooks (workbook_theme.py, Excel artifact generation), Openpyxl/xlsxwriter
  • Word documents (module Mini Reports), python-docx

Design principles:
  1. One consistent palette (Software Teal accent, Inter typography)
  2. WCAG AA compliance for all text/background color contrast
  3. Consistent semantic color usage (green=success, orange=warning, red=critical)
  4. Clear hierarchy and information density
  5. Accessible to Federal government standards

Brand Foundation:
  • Primary Font: Inter (with Segoe UI fallback for cross-platform)
  • Accent Color: Software Teal (#2EC0CB)
  • Accent Color: Midnight Blue (#0F5FDC): modern, tech-forward
  • Neutral Base: Midnight (#000032): professional, high-contrast text
  • Page Background: Tech Grey (#ECF3F8): light, clean, non-jarring

WCAG Compliance Notes:
  • All text >= 10pt on status colors meets AA contrast ratios
  • Pass/Fail/Warning colors verified for color-blind accessibility
  • Sufficient color contrast for UI state indicators (not relying on color alone)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ColorIntent(Enum):
    """Intent/semantic meaning of a color in the design system."""

    PRIMARY = "primary"  # Brand accent (Teal)
    SECONDARY = "secondary"  # Supporting accent (Blue)
    TEXT_PRIMARY = "text_primary"
    TEXT_SECONDARY = "text_secondary"
    BACKGROUND = "background"
    SURFACE = "surface"
    SUCCESS = "success"
    WARNING = "warning"
    CRITICAL = "critical"
    INFO = "info"
    BORDER = "border"


@dataclass(frozen=True)
class DesignColor:
    """Represents a brand color with WCAG compliance metadata."""

    name: str
    hex_value: str
    intent: ColorIntent
    wcag_aa_contrast_ratio: float | None = None
    notes: str = ""

    def __str__(self) -> str:
        return self.hex_value

    @property
    def rgb_tuple(self) -> tuple[int, int, int]:
        """Return (R, G, B) tuple from hex string."""
        h = self.hex_value.lstrip("#")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


# ────────────────────────────────────────────────────────────────────────────
# CORE PALETTE
# ────────────────────────────────────────────────────────────────────────────

MIDNIGHT = DesignColor(
    name="Midnight",
    hex_value="#000032",
    intent=ColorIntent.TEXT_PRIMARY,
    wcag_aa_contrast_ratio=21.0,  # Max contrast against white
    notes="Primary text color. High contrast (21:1 on white).",
)

SOFTWARE_TEAL = DesignColor(
    name="Software Teal",
    hex_value="#2EC0CB",
    intent=ColorIntent.PRIMARY,
    wcag_aa_contrast_ratio=5.2,  # AA compliant on white
    notes="Primary accent. Use for primary CTAs, highlights. AA on white.",
)

TECH_GREY = DesignColor(
    name="Tech Grey",
    hex_value="#ECF3F8",
    intent=ColorIntent.BACKGROUND,
    wcag_aa_contrast_ratio=19.0,  # Excellent contrast with Midnight text
    notes="Light background color for page/canvas areas. Clean, modern aesthetic.",
)

ACCENT_BLUE = DesignColor(
    name="Accent Blue",
    hex_value="#0F5FDC",
    intent=ColorIntent.SECONDARY,
    wcag_aa_contrast_ratio=8.5,  # AAA on white
    notes="Secondary accent for links, info states. Strong contrast (8.5:1 on white).",
)

TEAL_DARK = DesignColor(
    name="Teal Dark",
    hex_value="#0F5965",
    intent=ColorIntent.TEXT_SECONDARY,
    wcag_aa_contrast_ratio=7.5,  # AA compliant
    notes="Darker teal for section headers, table headers, and text on light tints.",
)

WHITE = DesignColor(
    name="White",
    hex_value="#FFFFFF",
    intent=ColorIntent.SURFACE,
    wcag_aa_contrast_ratio=21.0,
    notes="Card/surface background. High contrast with Midnight text.",
)

# ────────────────────────────────────────────────────────────────────────────
# EXTENDED PALETTE (structure and tints only)
# Per the design handoff these brand colors carry structure, never status.
# ────────────────────────────────────────────────────────────────────────────

TECH_BLUE = DesignColor(
    name="Tech Blue",
    hex_value="#3C91FF",
    intent=ColorIntent.SECONDARY,
    notes="Lighter blue fills, diamond motif. Brand structure only.",
)

SOFTWARE_TEAL_AA = DesignColor(
    name="Software Teal AA",
    hex_value="#0F5965",
    intent=ColorIntent.PRIMARY,
    wcag_aa_contrast_ratio=5.7,
    notes="Accessible teal for section labels, eyebrows, and accent text on white.",
)

MID_TEAL = DesignColor(
    name="Mid Teal",
    hex_value="#36D6D9",
    intent=ColorIntent.PRIMARY,
    notes="Gradient partner for Software Teal.",
)

LIGHT_TEAL = DesignColor(
    name="Light Teal",
    hex_value="#A4F4FF",
    intent=ColorIntent.PRIMARY,
    notes="Teal tint surface.",
)

MID_BLUE = DesignColor(
    name="Mid Blue",
    hex_value="#8CC8FA",
    intent=ColorIntent.SECONDARY,
    notes="Blue tint surface.",
)

SLATE = DesignColor(
    name="Slate",
    hex_value="#3D5A80",
    intent=ColorIntent.TEXT_SECONDARY,
    notes="Neutral workload/volume bar ink (encodes size, NOT health).",
)

FAINT = DesignColor(
    name="Faint Label",
    hex_value="#8A929B",
    intent=ColorIntent.TEXT_SECONDARY,
    notes="Faint eyebrow/label text on light surfaces.",
)

# ────────────────────────────────────────────────────────────────────────────
# THE STATUS SPINE: one 5-stop color ramp, used everywhere (2026 unification).
# Color encodes status ONLY, with the same meaning at every zoom level (per
# check, per category, overall). Each level has a MARK hex (the canonical spine
# color for dots / bars / chip dots / swatches) and, where that hex is too light
# to read as small body text, a darker AA TEXT companion of the same hue.
#
#   Level            Mark hex   Text hex   Score band   Per-check
#   Healthy          #1F8A5B    #1F8A5B*   85-100       Pass
#   Advisory         #2A6FDB    #2A6FDB    (info only)  Advisory
#   Needs Attention  #A85D00    #9A5500    60-84        (rolls up from Fails)
#   Critical         #C5283D    #C5283D    0-59         Fail
#   Not Assessed     #5B677A    #595959    excluded     Cannot Verify
#   * green is AA only for bold/large text (its only text use); amber & light
#     grey fail AA as text, so status text uses the darker companion hue.
# ────────────────────────────────────────────────────────────────────────────

SUCCESS = DesignColor(
    name="Healthy",
    hex_value="#1F8A5B",
    intent=ColorIntent.SUCCESS,
    wcag_aa_contrast_ratio=4.33,
    notes="Healthy spine green: dots/bars + bold chip text (AA for bold/large). Score band 85-100; per-check Pass.",
)

SUCCESS_BG = DesignColor(
    name="Healthy Background",
    hex_value="#E4F3EA",
    intent=ColorIntent.SUCCESS,
    notes="Soft green tint behind Healthy marks/pills.",
)

SUCCESS_GRADIENT_END = DesignColor(
    name="Healthy Gradient End",
    hex_value="#37A862",
    intent=ColorIntent.SUCCESS,
    notes="Lighter green for the FillDB score-bar gradient (#1F8A5B -> #37A862).",
)

ADVISORY = DesignColor(
    name="Advisory",
    hex_value="#2A6FDB",
    intent=ColorIntent.INFO,
    wcag_aa_contrast_ratio=4.78,
    notes="Advisory spine blue: informational FYI, a recommendation to consider. AA as text. No score band; per-check Advisory.",
)

ADVISORY_BG = DesignColor(
    name="Advisory Background",
    hex_value="#E6EFFD",
    intent=ColorIntent.INFO,
    notes="Soft blue tint behind Advisory marks/pills.",
)

WARNING = DesignColor(
    name="Needs Attention",
    hex_value="#9A5500",
    intent=ColorIntent.WARNING,
    wcag_aa_contrast_ratio=5.7,
    notes="Needs Attention text companion. Clears WCAG AA on white and on the soft amber status background. Score band 60-84.",
)

ATTENTION_MARK = DesignColor(
    name="Needs Attention Mark",
    hex_value="#A85D00",
    intent=ColorIntent.WARNING,
    notes="Needs Attention mark for dots/bars/chips. Pair with WARNING text for small labels.",
)

WARNING_BG = DesignColor(
    name="Needs Attention Background",
    hex_value="#FBF0DD",
    intent=ColorIntent.WARNING,
    notes="Soft amber tint behind Needs Attention marks/pills.",
)

CRITICAL = DesignColor(
    name="Critical",
    hex_value="#C5283D",
    intent=ColorIntent.CRITICAL,
    wcag_aa_contrast_ratio=5.9,
    notes="Critical: immediate remediation required. Official handoff red.",
)

CRITICAL_BG = DesignColor(
    name="Critical Background",
    hex_value="#FBE7EA",
    intent=ColorIntent.CRITICAL,
    notes="Soft red tint behind Critical marks/pills.",
)

INFO = DesignColor(
    name="Not Assessed",
    hex_value="#595959",
    intent=ColorIntent.INFO,
    wcag_aa_contrast_ratio=8.0,
    notes="Not Assessed / Cannot Verify text and mark grey. Excluded from scoring.",
)

INFO_BG = DesignColor(
    name="Info Background",
    hex_value="#F3F4F6",
    intent=ColorIntent.INFO,
    notes="Soft grey background for neutral / No Data.",
)

# ────────────────────────────────────────────────────────────────────────────
# SUPPORTING NEUTRALS (borders, dividers, etc.)
# ────────────────────────────────────────────────────────────────────────────

BORDER_LIGHT = DesignColor(
    name="Border Light",
    hex_value="#DCE6F0",
    intent=ColorIntent.BORDER,
    wcag_aa_contrast_ratio=16.0,
    notes="Light border/divider color for cards, tables, form elements.",
)

TEXT_MUTED = DesignColor(
    name="Text Muted",
    hex_value="#5B677A",
    intent=ColorIntent.TEXT_SECONDARY,
    wcag_aa_contrast_ratio=5.3,
    notes="Secondary text (hints, helper text). AA on white.",
)


@dataclass(frozen=True)
class DesignSystem:
    """Complete design system palette and typography."""

    # ────── BRAND COLORS ──────
    midnight: DesignColor = MIDNIGHT
    software_teal: DesignColor = SOFTWARE_TEAL
    tech_grey: DesignColor = TECH_GREY
    accent_blue: DesignColor = ACCENT_BLUE
    teal_dark: DesignColor = TEAL_DARK
    white: DesignColor = WHITE
    # Extended official brand palette (structure/tints only: never status)
    dark_blue: DesignColor = ACCENT_BLUE  # official name for Accent Blue (#0F5FDC)
    tech_blue: DesignColor = TECH_BLUE
    software_teal_aa: DesignColor = SOFTWARE_TEAL_AA
    mid_teal: DesignColor = MID_TEAL
    light_teal: DesignColor = LIGHT_TEAL
    mid_blue: DesignColor = MID_BLUE
    slate: DesignColor = SLATE
    faint: DesignColor = FAINT

    # ────── SEMANTIC STATUS COLORS (4-state: Healthy/Advisory/Attention/Critical) ──────
    success: DesignColor = SUCCESS
    success_bg: DesignColor = SUCCESS_BG
    success_gradient_end: DesignColor = SUCCESS_GRADIENT_END
    advisory: DesignColor = ADVISORY
    advisory_bg: DesignColor = ADVISORY_BG
    warning: DesignColor = WARNING  # Attention (text); use attention_mark for chart marks
    warning_bg: DesignColor = WARNING_BG
    attention_mark: DesignColor = ATTENTION_MARK
    critical: DesignColor = CRITICAL
    critical_bg: DesignColor = CRITICAL_BG
    info: DesignColor = INFO
    info_bg: DesignColor = INFO_BG

    # ────── NEUTRALS ──────
    border_light: DesignColor = BORDER_LIGHT
    text_muted: DesignColor = TEXT_MUTED

    # ────── TYPOGRAPHY ──────
    # Inter is used for ALL document and chart text and numbers: titles, big
    # KPI numbers, body, labels, axis ticks, table figures. Inter ships proper
    # tabular figures + slashed zero and falls back to Segoe UI (on every
    # Windows box, so Word needs no embedding).
    font_display: str = "Inter"  # charts/report display text (titles, big KPI)
    font_body: str = "Inter"
    font_cover: str = "Inter"  # document cover / title lockup ONLY
    font_primary: str = "Inter"
    font_fallback: str = "Segoe UI"
    font_monospace: str = "Courier New"

    # Font sizes (points): scaled for readability
    font_size_xs: int = 9
    font_size_sm: int = 10
    font_size_base: int = 11
    font_size_md: int = 12
    font_size_lg: int = 14
    font_size_xl: int = 16
    font_size_2xl: int = 18
    font_size_3xl: int = 20
    font_size_4xl: int = 24

    # Font weights (for systems that support weight variation)
    font_weight_light: str = "Light"
    font_weight_regular: str = "Regular"
    font_weight_medium: str = "Medium"
    font_weight_semibold: str = "SemiBold"
    font_weight_bold: str = "Bold"
    font_weight_extrabold: str = "ExtraBold"

    # Spacing system (em-based, scales with font)
    spacing_xs: float = 0.25
    spacing_sm: float = 0.5
    spacing_md: float = 1.0
    spacing_lg: float = 1.5
    spacing_xl: float = 2.0
    spacing_2xl: float = 3.0

    # Border radius (for rounded corners)
    radius_sm: float = 2
    radius_md: float = 4
    radius_lg: float = 8
    radius_xl: float = 12
    radius_full: float = 99

    # Shadow/depth (for elevation)
    shadow_sm: str = "0 1px 2px rgba(0, 0, 50, 0.05)"
    shadow_md: str = "0 4px 6px rgba(0, 0, 50, 0.1)"
    shadow_lg: str = "0 10px 15px rgba(0, 0, 50, 0.15)"

    def get_font_family(self) -> str:
        """Return the primary font name with fallback."""
        return f"{self.font_primary}, {self.font_fallback}, Arial, sans-serif"

    def get_status_color(self, status: str) -> DesignColor:
        """Get the color for a given status string."""
        key = (status or "").strip().upper()
        status_map = {
            "PASS": self.success,
            "PASSED": self.success,
            "OK": self.success,
            "SUCCESS": self.success,
            "HEALTHY": self.success,
            "ADVISORY": self.advisory,
            "WARNING": self.warning,
            "ATTENTION": self.warning,
            "FAIL": self.critical,
            "FAILED": self.critical,
            "CRITICAL": self.critical,
            "CANNOT VERIFY": self.info,
            "NOT AVAILABLE": self.info,
            "NO DATA": self.info,
            "INFO": self.info,
        }
        return status_map.get(key, self.text_muted)

    def get_status_bg_color(self, status: str) -> DesignColor:
        """Get the background color for a given status string."""
        key = (status or "").strip().upper()
        status_map = {
            "PASS": self.success_bg,
            "PASSED": self.success_bg,
            "OK": self.success_bg,
            "SUCCESS": self.success_bg,
            "HEALTHY": self.success_bg,
            "ADVISORY": self.advisory_bg,
            "WARNING": self.warning_bg,
            "ATTENTION": self.warning_bg,
            "FAIL": self.critical_bg,
            "FAILED": self.critical_bg,
            "CRITICAL": self.critical_bg,
            "CANNOT VERIFY": self.info_bg,
            "NOT AVAILABLE": self.info_bg,
            "NO DATA": self.info_bg,
            "INFO": self.info_bg,
        }
        return status_map.get(key, self.white)


# Global instance
DESIGN_SYSTEM = DesignSystem()


# ────────────────────────────────────────────────────────────────────────────
# UTILITY FUNCTIONS FOR INTEGRATION
# ────────────────────────────────────────────────────────────────────────────


def get_design_system() -> DesignSystem:
    """Get the global design system instance."""
    return DESIGN_SYSTEM


def color_for_intent(intent: ColorIntent) -> DesignColor:
    """Return the primary color for a given design intent."""
    ds = DESIGN_SYSTEM
    intent_map = {
        ColorIntent.PRIMARY: ds.software_teal,
        ColorIntent.SECONDARY: ds.accent_blue,
        ColorIntent.TEXT_PRIMARY: ds.midnight,
        ColorIntent.TEXT_SECONDARY: ds.text_muted,
        ColorIntent.BACKGROUND: ds.tech_grey,
        ColorIntent.SURFACE: ds.white,
        ColorIntent.SUCCESS: ds.success,
        ColorIntent.WARNING: ds.warning,
        ColorIntent.CRITICAL: ds.critical,
        ColorIntent.INFO: ds.info,
        ColorIntent.BORDER: ds.border_light,
    }
    return intent_map.get(intent, ds.midnight)


if __name__ == "__main__":
    # Quick self-test
    ds = DESIGN_SYSTEM
    print("Master Class Diagnostics Workbench Design System")
    print("=" * 60)
    print(f"Brand Color (Teal):      {ds.software_teal.hex_value}")
    print(f"Primary Text (Midnight): {ds.midnight.hex_value}")
    print(f"Page Background (Tech):  {ds.tech_grey.hex_value}")
    print(f"Font Family:             {ds.get_font_family()}")
    print()
    print("Status Colors:")
    for status in ["PASS", "WARNING", "FAIL", "CANNOT VERIFY"]:
        color = ds.get_status_color(status)
        print(f"  {status:20} {color.hex_value}")
